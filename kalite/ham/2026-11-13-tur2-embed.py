import os,sys,time,pickle
E=sys.argv[1]; os.environ["HF_HOME"]=E+"/hf"
import numpy as np, torch
from sentence_transformers import SentenceTransformer
mid,txt=pickle.load(open(E+"/chunks.pkl","rb"))
m=SentenceTransformer("BAAI/bge-m3",device="cuda"); m.max_seq_length=512; m.half()
N=len(txt); S=8; step=(N+S-1)//S
t0=time.time()
for s in range(S):
    fn=E+f"/npy/chunk_{s}.npy"
    if os.path.exists(fn): continue
    a=txt[s*step:(s+1)*step]
    v=m.encode(a,batch_size=64,normalize_embeddings=True,convert_to_numpy=True)
    np.save(fn,v.astype(np.float16)); print(s,time.time()-t0,flush=True)
open(E+"/embed_done.txt","w").write(str(time.time()-t0))
