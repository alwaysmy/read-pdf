"""CPU adapter for PaddlePaddle's official PP-DocLayoutV3 ONNX export.

No download, remote code, Paddle runtime, or model conversion occurs here.
Preprocessing and ordered-box semantics follow the official inference.yml and
PaddleX detection processor. Masks are not exposed as polygon truth.
"""
import pathlib

import cv2
import numpy as np
import yaml
from openvino import Core


def _iou(a,b):
    ix=max(0,min(a[2],b[2])-max(a[0],b[0]));iy=max(0,min(a[3],b[3])-max(a[1],b[1]))
    intersection=ix*iy
    return intersection/max(1e-6,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection)


class DocLayoutOpenVINO:
    def __init__(self, model_dir, device='cpu'):
        if device!='cpu':
            raise ValueError('OpenVINO layout adapter currently supports explicit CPU only')
        directory=pathlib.Path(model_dir).expanduser()
        model=directory/'inference.onnx';configuration=directory/'inference.yml'
        if not model.is_file() or not configuration.is_file():
            raise FileNotFoundError('layout_ov_dir must contain official inference.onnx and inference.yml')
        config=yaml.safe_load(configuration.read_text(encoding='utf-8'))
        self.labels=config['label_list']
        if config.get('Global',{}).get('model_name')!='PP-DocLayoutV3':
            raise ValueError('Only official PP-DocLayoutV3 export is supported')
        preprocessing=config.get('Preprocess',[])
        if (len(preprocessing)!=3 or preprocessing[0].get('target_size')!=[800,800]
                or preprocessing[0].get('keep_ratio') is not False
                or preprocessing[0].get('interp')!=2
                or preprocessing[1].get('mean')!=[0.0,0.0,0.0]
                or preprocessing[1].get('std')!=[1.0,1.0,1.0]
                or preprocessing[1].get('norm_type')!='none'
                or preprocessing[2].get('type')!='Permute'):
            raise ValueError('Unsupported layout preprocessing contract')
        core=Core();self.compiled=core.compile_model(core.read_model(str(model)),'CPU')
        self.inputs={port.any_name for port in self.compiled.inputs}
        if self.inputs!={'im_shape','image','scale_factor'}:
            raise ValueError('Unexpected PP-DocLayoutV3 ONNX input contract')

    def predict(self,img_path):
        image=cv2.imread(str(img_path))
        if image is None:raise ValueError(f'Cannot read layout image: {img_path}')
        height,width=image.shape[:2]
        tensor=cv2.resize(cv2.cvtColor(image,cv2.COLOR_BGR2RGB),(800,800),interpolation=cv2.INTER_CUBIC)
        feed={'image':np.ascontiguousarray(tensor.astype(np.float32).transpose(2,0,1)[None]/255),
              'im_shape':np.array([[800,800]],dtype=np.float32),
              'scale_factor':np.array([[800/height,800/width]],dtype=np.float32)}
        result=self.compiled(feed)
        raw=next(value for value in result.values() if value.ndim==2 and value.shape[1]==7)
        candidates=[]
        for row in raw:
            cls,score=int(row[0]),float(row[1])
            if score<0.3 or not 0<=cls<len(self.labels) or not np.isfinite(row).all():continue
            x0,y0,x1,y1=[float(v) for v in row[2:6]]
            bbox=[max(0,x0),max(0,y0),min(width,x1),min(height,y1)]
            if bbox[0]>=bbox[2] or bbox[1]>=bbox[3]:continue
            candidates.append({'label':self.labels[cls],'score':score,'coordinate':bbox,
                               'reading_order':int(row[6])})
        kept=[]
        for box in sorted(candidates,key=lambda item:-item['score']):
            if any(_iou(box['coordinate'],other['coordinate'])>(0.6 if box['label']==other['label'] else 0.98)
                   for other in kept):continue
            kept.append(box)
        if len(kept)>1:
            threshold=0.82 if width>height else 0.93
            filtered=[box for box in kept if box['label']!='image' or
                      (box['coordinate'][2]-box['coordinate'][0])*(box['coordinate'][3]-box['coordinate'][1])<threshold*width*height]
            kept=filtered or kept
        # Ordered detectors may propose both a complete table and its subsections.
        # Keep containing regions of the same class instead of duplicating content.
        def contained(inner,outer):
            a,b=inner['coordinate'],outer['coordinate']
            area=(a[2]-a[0])*(a[3]-a[1]);big=(b[2]-b[0])*(b[3]-b[1])
            overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
            return big>area*1.05 and overlap/max(1,area)>0.98
        kept=[box for box in kept if not any(other is not box and other['label']==box['label']
                                             and other['score']>=0.5 and contained(box,other) for other in kept)]
        yield {'boxes':sorted(kept,key=lambda item:item['reading_order']),
               'backend':'openvino','model':'PP-DocLayoutV3'}


def create_model(model_dir,device='cpu'):
    return DocLayoutOpenVINO(model_dir,device)
