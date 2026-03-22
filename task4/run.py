"""NorgesGruppen — Multi-model ONNX ensemble with NMS
Best score: 0.9024 mAP with v19_fp16 + v20_fp16 + v8x (3 models)
Supports FP16 and FP32 ONNX models automatically."""
import json, argparse, numpy as np
from pathlib import Path
import onnxruntime as ort
from PIL import Image

def preprocess(img, imgsz=1280):
    ow,oh=img.size; s=min(imgsz/ow,imgsz/oh)
    nw,nh=int(ow*s),int(oh*s)
    r=img.resize((nw,nh),Image.BILINEAR)
    c=Image.new("RGB",(imgsz,imgsz),(114,114,114))
    px,py=(imgsz-nw)//2,(imgsz-nh)//2
    c.paste(r,(px,py))
    a=np.array(c,dtype=np.float32)/255.0
    return a.transpose(2,0,1)[np.newaxis],ow,oh,s,px,py

def nms(boxes,scores,t=0.5):
    if len(boxes)==0: return []
    x1,y1,x2,y2=boxes[:,0],boxes[:,1],boxes[:,2],boxes[:,3]
    areas=(x2-x1)*(y2-y1); order=scores.argsort()[::-1]; keep=[]
    while len(order)>0:
        i=order[0]; keep.append(i)
        if len(order)==1: break
        xx1=np.maximum(x1[i],x1[order[1:]]); yy1=np.maximum(y1[i],y1[order[1:]])
        xx2=np.minimum(x2[i],x2[order[1:]]); yy2=np.minimum(y2[i],y2[order[1:]])
        inter=np.maximum(0,xx2-xx1)*np.maximum(0,yy2-yy1)
        iou=inter/(areas[i]+areas[order[1:]]-inter+1e-6)
        order=order[1:][iou<=t]
    return keep

def decode(out,ow,oh,s,px,py,conf=0.001):
    p=out[0]
    if len(p.shape)==3: p=p[0]
    if p.shape[0]<p.shape[1]: p=p.T
    b,sc=p[:,:4],p[:,4:]; ms=sc.max(axis=1); m=ms>=conf
    b,ms,ci=b[m],ms[m],sc[m].argmax(axis=1)
    if len(b)==0: return np.zeros((0,4)),np.zeros(0),np.zeros(0,dtype=int)
    cx,cy,bw,bh=b[:,0],b[:,1],b[:,2],b[:,3]
    x1=np.clip((cx-bw/2-px)/s,0,ow); y1=np.clip((cy-bh/2-py)/s,0,oh)
    x2=np.clip((cx+bw/2-px)/s,0,ow); y2=np.clip((cy+bh/2-py)/s,0,oh)
    return np.stack([x1,y1,x2,y2],axis=1),ms,ci

def img_id(f):
    d=''.join(c for c in Path(f).stem if c.isdigit())
    return int(d) if d else 0

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    inp=Path(args.input); out=Path(args.output); sd=Path(__file__).parent
    prov=["CUDAExecutionProvider","CPUExecutionProvider"]
    
    # Load all models
    models=[]
    for name in ["model_a.onnx","model_b.onnx","model_c.onnx"]:
        p=sd/name
        if p.exists():
            sess=ort.InferenceSession(str(p),providers=prov)
            models.append((sess,sess.get_inputs()[0].name,sess.get_inputs()[0].shape[2]))
    
    files=sorted([f for f in inp.iterdir() if f.suffix.lower() in ('.jpg','.jpeg','.png')])
    preds=[]
    for fp in files:
        iid=img_id(fp.name)
        img=Image.open(str(fp)).convert("RGB")
        ow,oh=img.size
        all_b,all_s,all_c=[],[],[]
        for sess,nm,imgsz in models:
            arr,_,_,s,px,py=preprocess(img,imgsz)
            if 'float16' in sess.get_inputs()[0].type:
                arr=arr.astype(np.float16)
            o=sess.run(None,{nm:arr})
            b,sc,cl=decode(o[0],ow,oh,s,px,py)
            if len(b)>0: all_b.append(b); all_s.append(sc); all_c.append(cl)
        if not all_b: continue
        ab=np.concatenate(all_b); asc=np.concatenate(all_s); ac=np.concatenate(all_c)
        keep=nms(ab,asc,0.5)
        for i in keep:
            x1,y1,x2,y2=ab[i]; w=x2-x1; h=y2-y1
            if w>1 and h>1:
                preds.append({"image_id":iid,"category_id":int(ac[i]),"bbox":[round(float(x1),1),round(float(y1),1),round(float(w),1),round(float(h),1)],"score":round(float(asc[i]),3)})
    out.parent.mkdir(parents=True,exist_ok=True)
    with open(out,'w') as f: json.dump(preds,f)
    print(f"Done: {len(files)} images, {len(preds)} detections, {len(models)} models")

if __name__=="__main__": main()
