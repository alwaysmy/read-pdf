"""Geometry/assembly regressions; no model or remote service needed."""
import pathlib
import sys
import tempfile
import unittest

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
if cv2 is not None:
    from ruled_tables import reconstruct_table,render_table,refine_min_typ_max
import extract_pdf as ep


def fixture(merged=False):
    image=np.full((180,350,3),255,dtype=np.uint8)
    xs=[10,130,230,330];ys=[10,60,110,160]
    for y in ys:cv2.line(image,(10,y),(330,y),(0,0,0),2)
    for x in xs:cv2.line(image,(x,60 if merged and x in xs[1:-1] else 10),(x,160),(0,0,0),2)
    rows=[['Name','Min','Max'],['Repeated','0','2'],['Repeated','0','2']]
    if merged:rows[0]=['Merged','','']
    lines=[]
    for r,row in enumerate(rows):
        for c,text in enumerate(row):
            if text:lines.append({'text':text,'bbox':[xs[c]+10,ys[r]+15,xs[c]+65,ys[r]+35]})
    return image,lines,rows


@unittest.skipIf(cv2 is None, 'optional OpenCV runtime is not installed')
class RuledTableTests(unittest.TestCase):
    def test_exact_values_and_duplicate_rows(self):
        image,lines,expected=fixture();table=reconstruct_table(image,[8,8,332,162],lines)
        self.assertEqual(table['matrix'],expected);self.assertEqual(table['quality_flags'],[])
        self.assertEqual(render_table(table).count('<td>Repeated</td>'),2)

    def test_visible_merged_header(self):
        image,lines,expected=fixture(True);table=reconstruct_table(image,[8,8,332,162],lines)
        self.assertEqual(table['matrix'],expected)
        self.assertEqual(table['cells'][0]['colspan'],3)
        self.assertIn('colspan="3"',render_table(table))

    def test_borderless_fails_closed(self):
        image,lines,_=fixture();image[:]=255
        self.assertIsNone(reconstruct_table(image,[8,8,332,162],lines))

    def test_unassigned_text_survives(self):
        image,lines,_=fixture();lines.append({'text':'ACROSS CELLS','bbox':[80,80,285,95]})
        table=reconstruct_table(image,[8,8,332,162],lines)
        self.assertIn('table_text_unassigned',table['quality_flags'])
        self.assertIn('ACROSS CELLS',render_table(table))

    def test_implicit_columns_are_flagged(self):
        image,lines,_=fixture(True)
        lines=[line for line in lines if line['text']!='Merged']
        lines.extend([{'text':'Min','bbox':[35,25,70,45]},{'text':'Max','bbox':[265,25,300,45]}])
        table=reconstruct_table(image,[8,8,332,162],lines)
        self.assertIn('table_columns_ambiguous',table['quality_flags'])
        self.assertEqual(table['cells'][0]['text'],'Min Max')

    def test_html_is_escaped(self):
        image,lines,_=fixture();lines[0]['text']='x < y & z'
        result=render_table(reconstruct_table(image,[8,8,332,162],lines))
        self.assertIn('x &lt; y &amp; z',result)

    def test_blank_cells_preserved(self):
        image,lines,_=fixture();lines=[line for line in lines if line['text']!='0']
        table=reconstruct_table(image,[8,8,332,162],lines)
        self.assertEqual(table['matrix'][1][1],'')
        self.assertEqual(table['matrix'][2][1],'')

    def test_model_reading_order_preserved(self):
        blocks=[{'bbox':[0,0,100,20],'reading_order':8},{'bbox':[100,50,200,80],'reading_order':2}]
        self.assertEqual([b['reading_order'] for b in ep._reading_order(blocks,200)],[2,8])

    def test_header_alignment_never_claims_visible_grid(self):
        table={'rows':2,'columns':1,'cells':[
            {'row':0,'column':0,'rowspan':1,'colspan':1,'bbox':[0,0,300,50],'text':'MIN TYP MAX'},
            {'row':1,'column':0,'rowspan':1,'colspan':1,'bbox':[0,50,300,100],'text':'-3 ±1 3'}],
            'matrix':[['MIN TYP MAX'],['-3 ±1 3']],'quality_flags':['table_columns_ambiguous'],'unassigned_text':[]}
        lines=[{'text':text,'bbox':[x,top,x+30,top+20]} for top,row in [(10,['MIN','TYP','MAX']),(65,['-3','±1','3'])]
               for x,text in zip([20,130,240],row)]
        refined=refine_min_typ_max(table,lines)
        self.assertEqual(refined['matrix'],[['MIN','TYP','MAX'],['-3','±1','3']])
        self.assertIn('table_columns_inferred_from_headers',refined['quality_flags'])
        self.assertIn('table_columns_ambiguous',refined['quality_flags'])

    def test_suspicious_unit_is_flagged_not_rewritten(self):
        flags,status=ep._page_quality('value 25°℃',{}, {'blank':False},'hybrid')
        self.assertIn('suspicious_unit_symbol',flags);self.assertEqual(status,'needs_review')

    def test_nested_inline_formula_does_not_duplicate_text_or_crops(self):
        with tempfile.TemporaryDirectory() as directory:
            image=pathlib.Path(directory)/'page.png';cv2.imwrite(str(image),np.full((100,200,3),255,np.uint8))
            text,stats=ep._merge_lines_with_layout([{'text':'Value is x 2 + y','bbox':[10,10,180,35]}],
              [{'label':'text','bbox':[0,0,190,50],'score':.9},
               {'label':'inline_formula','bbox':[70,10,180,35],'score':.9}],image)
        self.assertEqual(text.count('Value is x 2 + y'),1)
        self.assertNotIn('readpdf-region',text)
        self.assertEqual(len(stats['inline_formula_regions']),1)
        self.assertEqual(len(stats['layout_blocks']),1)

    def test_empty_ocr_cannot_be_hidden_by_generated_table_markup(self):
        text,stats=ep._merge_lines_with_layout([], [{'label':'table','bbox':[0,0,100,50],'score':.9}], 'unused.png')
        self.assertEqual(text,'')
        self.assertIn('empty_extraction',stats['quality_flags'])
        self.assertIn('error',stats)

    def test_formula_is_not_fabricated_latex(self):
        with tempfile.TemporaryDirectory() as directory:
            image=pathlib.Path(directory)/'page.png';cv2.imwrite(str(image),np.full((100,200,3),255,np.uint8))
            text,stats=ep._merge_lines_with_layout([{'text':'x 2 + y','bbox':[10,10,90,35]}],
                          [{'label':'display_formula','bbox':[0,0,100,50],'score':.9}],image)
        self.assertNotIn('$$',text)
        self.assertIn('formula_structure_unverified',stats['quality_flags'])
        self.assertIn('x 2 + y',text)


if __name__=='__main__':unittest.main()
