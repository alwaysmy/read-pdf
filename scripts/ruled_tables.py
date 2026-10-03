"""Conservative reconstruction of visibly ruled cells, without semantic repair.

Boundaries come from image lines, text from existing OCR boxes. Merged cells are
only emitted for rectangular connected regions. Borderless/ambiguous tables fail
closed, leaving the caller's original OCR text available for review.
"""
import html

import cv2
import numpy as np


def _centres(values):
    groups=[]
    for value in values:
        if groups and value<=groups[-1][-1]+2:groups[-1].append(int(value))
        else:groups.append([int(value)])
    return [int(round(sum(group)/len(group))) for group in groups]


def _iou_text(line,cell):
    x0,y0,x1,y1=line;x2,y2,x3,y3=cell
    return max(0,min(x1,x3)-max(x0,x2))*max(0,min(y1,y3)-max(y0,y2))/max(1,(x1-x0)*(y1-y0))


def reconstruct_table(image,bbox,lines):
    if image is None:return None
    height,width=image.shape[:2]
    x0,y0,x1,y1=bbox
    left,top=max(0,int(x0)-8),max(0,int(y0)-8)
    right,bottom=min(width,int(x1)+9),min(height,int(y1)+9)
    gray=cv2.cvtColor(image[top:bottom,left:right],cv2.COLOR_BGR2GRAY)
    if gray.size==0:return None
    h,w=gray.shape
    binary=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_MEAN_C,cv2.THRESH_BINARY_INV,15,12)
    horizontal=cv2.morphologyEx(binary,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(max(25,w//15),1)))
    heights=[line['bbox'][3]-line['bbox'][1] for line in lines if line.get('bbox')]
    # Short header/row dividers must survive even in a tall multipage-style table.
    vertical_length=max(12,int(np.median(heights)*1.2)) if heights else 20
    vertical=cv2.morphologyEx(binary,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(1,vertical_length)))
    xs=_centres(np.where((vertical>0).sum(axis=0)>=max(20,h*0.15))[0])
    ys=_centres(np.where((horizontal>0).sum(axis=1)>=max(25,w*0.15))[0])
    if not (3<=len(xs)<=40 and 3<=len(ys)<=150):return None
    rows,cols=len(ys)-1,len(xs)-1
    if min(np.diff(xs))<10 or min(np.diff(ys))<8:return None
    parent=list(range(rows*cols))
    def find(index):
        while parent[index]!=index:
            parent[index]=parent[parent[index]];index=parent[index]
        return index
    def merge(a,b):parent[find(b)]=find(a)
    def vertical_present(x,ya,yb):
        region=vertical[ya+3:yb-2,max(0,x-2):x+3]
        return region.size and (region.max(axis=1)>0).mean()>=0.45
    def horizontal_present(y,xa,xb):
        region=horizontal[max(0,y-2):y+3,xa+3:xb-2]
        return region.size and (region.max(axis=0)>0).mean()>=0.45
    # Require every outside edge; disconnected whitespace must not become a cell.
    if any(not vertical_present(x,ys[0],ys[-1]) for x in (xs[0],xs[-1])):return None
    if any(not horizontal_present(y,xs[0],xs[-1]) for y in (ys[0],ys[-1])):return None
    for r in range(rows):
        for c in range(cols):
            if c+1<cols and not vertical_present(xs[c+1],ys[r],ys[r+1]):merge(r*cols+c,r*cols+c+1)
            if r+1<rows and not horizontal_present(ys[r+1],xs[c],xs[c+1]):merge(r*cols+c,(r+1)*cols+c)
    groups={}
    for r in range(rows):
        for c in range(cols):groups.setdefault(find(r*cols+c),[]).append((r,c))
    cells=[]
    for members in groups.values():
        r0=min(r for r,c in members);r1=max(r for r,c in members)
        c0=min(c for r,c in members);c1=max(c for r,c in members)
        if len(members)!=(r1-r0+1)*(c1-c0+1):return None
        cells.append({'row':r0,'column':c0,'rowspan':r1-r0+1,'colspan':c1-c0+1,
                      'bbox':[left+xs[c0],top+ys[r0],left+xs[c1+1],top+ys[r1+1]],'lines':[]})
    unassigned=[]
    for line in lines:
        if not line.get('bbox'):unassigned.append(line);continue
        ranked=sorted(((_iou_text(line['bbox'],cell['bbox']),i) for i,cell in enumerate(cells)),reverse=True)
        if ranked and ranked[0][0]>=0.65:
            cells[ranked[0][1]]['lines'].append(line)
        else:unassigned.append(line)
    # Text not confidently contained in one visible cell must never be discarded.
    flags=['table_text_unassigned'] if unassigned else []
    for cell in cells:
        text_lines=cell.pop('lines');bands=[]
        for line in sorted(text_lines,key=lambda item:(item['bbox'][1]+item['bbox'][3])/2):
            box=line['bbox'];cy=(box[1]+box[3])/2;line_height=box[3]-box[1]
            if bands and abs(cy-bands[-1][0])<=max(3,line_height*0.45):bands[-1][1].append(line)
            else:bands.append((cy,[line]))
        rows_text=[]
        for _,band in bands:
            band.sort(key=lambda item:item['bbox'][0])
            for previous,current in zip(band,band[1:]):
                gap=current['bbox'][0]-previous['bbox'][2]
                height=max(previous['bbox'][3]-previous['bbox'][1],current['bbox'][3]-current['bbox'][1])
                if gap>height*1.5:flags.append('table_columns_ambiguous')
            rows_text.append(' '.join(line['text'] for line in band))
        cell['text']='\n'.join(rows_text)
    flags=sorted(set(flags))
    cells.sort(key=lambda cell:(cell['row'],cell['column']))
    matrix=[['' for _ in range(cols)] for _ in range(rows)]
    for cell in cells:matrix[cell['row']][cell['column']]=cell['text']
    return {'rows':rows,'columns':cols,'cells':cells,'matrix':matrix,'quality_flags':flags,
            'unassigned_text':[line['text'] for line in unassigned],
            'bbox':[left+xs[0],top+ys[0],left+xs[-1],top+ys[-1]],
            'method':'visible_grid_and_ocr_boxes','validation_state':'unverified'}


def render_table(table):
    parts=['<table>']
    for row in range(table['rows']):
        parts.append('<tr>')
        for cell in table['cells']:
            if cell['row']!=row:continue
            spans=''.join(f' {key}="{cell[key]}"' for key in ('rowspan','colspan') if cell[key]>1)
            parts.append(f'<td{spans}>{html.escape(cell["text"]).replace(chr(10),"<br>")}</td>')
        parts.append('</tr>')
    parts.append('</table>')
    if table['unassigned_text']:
        parts.append('\n<!-- Unassigned table text; cell placement requires review -->\n'+'\n'.join(table['unassigned_text']))
    return '\n'.join(parts)


def refine_min_typ_max(table,lines):
    """Optional geometric split from an explicitly recognized MIN/TYP/MAX header.

    This is an inferred alignment, always flagged. It never derives values from
    semantics, fills missing cells, or changes OCR characters.
    """
    headers={}
    for line in lines:
        label=line['text'].strip().upper().rstrip('.')
        if label in ('MIN','TYP','MAX') and line.get('bbox'):
            if label in headers:return table
            headers[label]=line
    if set(headers)!= {'MIN','TYP','MAX'}:return table
    ordered=[headers[name] for name in ('MIN','TYP','MAX')]
    centres=[(line['bbox'][0]+line['bbox'][2])/2 for line in ordered]
    ys=[(line['bbox'][1]+line['bbox'][3])/2 for line in ordered]
    if centres!=sorted(centres) or max(ys)-min(ys)>max(line['bbox'][3]-line['bbox'][1] for line in ordered)*.5:return table
    header=next((cell for cell in table['cells'] if cell['row']<=1 and cell['colspan']==1
                 and all(_iou_text(line['bbox'],cell['bbox'])>.65 for line in ordered)),None)
    if header is None:return table
    column=header['column'];cuts=[(centres[0]+centres[1])/2,(centres[1]+centres[2])/2]
    if not header['bbox'][0]<cuts[0]<cuts[1]<header['bbox'][2]:return table
    cells=[]
    extra_unassigned=[]
    for original in table['cells']:
        cell=dict(original);start=cell['column'];stop=start+cell['colspan']
        if start>column:
            cell['column']+=2;cells.append(cell);continue
        if start!=column or cell['colspan']!=1:
            if start<=column<stop:cell['colspan']+=2
            cells.append(cell);continue
        bounds=[cell['bbox'][0],*cuts,cell['bbox'][2]]
        groups=[[0],[1],[2]]
        selected=[line for line in lines if line.get('bbox') and _iou_text(line['bbox'],cell['bbox'])>=.65]
        # Long source strings may visibly span numeric columns; retain that span.
        for line in selected:
            scores=[_iou_text(line['bbox'],[bounds[i],cell['bbox'][1],bounds[i+1],cell['bbox'][3]]) for i in range(3)]
            touched=[i for i,score in enumerate(scores) if score>.1]
            if max(scores)<.65 and len(touched)>1:
                combined=sorted({i for group in groups if any(j in group for j in touched) for i in group})
                groups=[group for group in groups if not set(group)&set(combined)]+[combined]
        used=set()
        for group in sorted(groups):
            lo,hi=min(group),max(group)
            bbox=[bounds[lo],cell['bbox'][1],bounds[hi+1],cell['bbox'][3]]
            assigned=[line for line in selected if _iou_text(line['bbox'],bbox)>=.65]
            # Preserve baseline order and characters; this is not language repair.
            assigned.sort(key=lambda line:(round(((line['bbox'][1]+line['bbox'][3])/2)/12),line['bbox'][0]))
            used.update(id(line) for line in assigned)
            cells.append({**cell,'column':column+lo,'colspan':hi-lo+1,'bbox':bbox,
                          'text':'\n'.join(line['text'] for line in assigned),
                          'method':'inferred_from_explicit_MIN_TYP_MAX_header'})
        extra_unassigned.extend(line['text'] for line in selected if id(line) not in used)
    table=dict(table,cells=sorted(cells,key=lambda cell:(cell['row'],cell['column'])),columns=table['columns']+2)
    table['matrix']=[['' for _ in range(table['columns'])] for _ in range(table['rows'])]
    for cell in table['cells']:table['matrix'][cell['row']][cell['column']]=cell['text']
    table['quality_flags']=sorted(set(table['quality_flags']+['table_columns_inferred_from_headers']))
    table['unassigned_text']=table['unassigned_text']+extra_unassigned
    if extra_unassigned:table['quality_flags'].append('table_text_unassigned')
    table['inferred_vertical_boundaries']=cuts
    return table
