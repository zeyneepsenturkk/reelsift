import os,sys,time,pickle,json,glob
E=sys.argv[1]; os.environ["HF_HOME"]=E+"/hf"
import numpy as np, pandas as pd, torch
from sentence_transformers import SentenceTransformer, CrossEncoder
from scipy.stats import spearmanr
dev="cuda"
df=pd.read_csv(E+"/../dl/final_dataset.csv",low_memory=False)
ids=np.load(E+"/npy/final_dense_movie_ids.npy",allow_pickle=True)
assert (df.movie_id.values==ids).all()
X=torch.tensor(np.load(E+"/npy/final_dense_embeddings.npy").astype(np.float32),device=dev)
mid,txt=pickle.load(open(E+"/chunks.pkl","rb"))
C=torch.tensor(np.concatenate([np.load(E+f"/npy/chunk_{s}.npy") for s in range(8)]),device=dev)
assert C.shape[0]==len(txt)
mid_t=torch.tensor(mid,device=dev); NF=len(df)
m2i={x:i for i,x in enumerate(ids)}
B=json.load(open(E+"/b.json",encoding="utf-8"))+json.load(open(E+"/b2.json",encoding="utf-8"))
assert len(B)==50
tgt=[m2i[b["id"]] for b in B]
vote=df.vote_count.fillna(0).values; PL=df.plot_length_chars.values
known=np.array([vote[t]>=1000 for t in tgt]); long_=np.array([PL[t]>=3000 for t in tgt])
model=SentenceTransformer("BAAI/bge-m3",device=dev); model.max_seq_length=512
def enc(L): return torch.tensor(model.encode(list(L),batch_size=16,normalize_embeddings=True,convert_to_numpy=True),device=dev)
QT=enc([b["tr"] for b in B]); QE=enc([b["en"] for b in B])
Cf=C.float()
def single(q): return X@q
def chunk(q):
    s=Cf@q
    out=torch.full((NF,),-9.0,device=dev); out.scatter_reduce_(0,mid_t,s,"amax",include_self=True); return out
def rank_of(s,t): return int((s>s[t]).sum().item())+1
def metr(r):
    r=np.array(r); return dict(R1=float((r<=1).mean()),R10=float((r<=10).mean()),R50=float((r<=50).mean()),med=float(np.median(r)),n=len(r))
def fmt(name,r):
    r=np.array(r); out=[]
    for g,mk in [("hepsi",np.ones(50,bool)),("bilinen",known),("az bilinen",~known),("kisa plot",~long_),("uzun plot",long_),
                 ("bilinen+kisa",known&~long_),("bilinen+uzun",known&long_),("azbil+kisa",~known&~long_),("azbil+uzun",~known&long_)]:
        if mk.sum()==0: continue
        m=metr(r[mk]); out.append(f"| {name} | {g} | {m['n']} | {m['R1']:.2f} | {m['R10']:.2f} | {m['R50']:.2f} | {m['med']:.0f} |")
    return out
SC={}
ranks={}
t0=time.time()
for name,Q,fn in [("V0",QT,single),("V1",QE,single),("V2",QT,chunk),("V3",QE,chunk)]:
    r=[]
    for k in range(50):
        s=fn(Q[k]); SC[(name,k)]=s; r.append(rank_of(s,tgt[k]))
    ranks[name]=r
def fuse(name,f):
    r=[]
    for k in range(50):
        s=f(k); SC[(name,k)]=s; r.append(rank_of(s,tgt[k]))
    ranks[name]=r
fuse("V5a(V2+V0 0.5/0.5)",lambda k:0.5*SC[("V2",k)]+0.5*SC[("V0",k)])
fuse("V5b(V3+V1 0.5/0.5)",lambda k:0.5*SC[("V3",k)]+0.5*SC[("V1",k)])
fuse("V5c(V2+V3, TR+EN sorgu)",lambda k:SC[("V2",k)]+SC[("V3",k)])
fuse("V5d(V0+V1+V2+V3)",lambda k:SC[("V0",k)]+SC[("V1",k)]+SC[("V2",k)]+SC[("V3",k)])
res=["| varyant | grup | n | R@1 | R@10 | R@50 | medyan sira |","|---|---|---|---|---|---|---|"]
for n in list(ranks): res+=fmt(n,ranks[n])
def key(n):
    m=metr(ranks[n]); return (m["R10"],m["R1"],-m["med"])
best=max(["V2","V3"],key=key); print("best",best,flush=True)
tab=["| id | film | yil | vote | plot_len | bilinen | V0 | V1 | V2 | V3 |","|---|---|---|---|---|---|---|---|---|---|"]
for k,b in enumerate(B):
    i=tgt[k]; tab.append(f"| {b['id']} | {df.title.iloc[i]} | {int(df.year.iloc[i])} | {int(vote[i])} | {int(PL[i])} | {bool(known[k])} | "+" | ".join(str(ranks[v][k]) for v in ["V0","V1","V2","V3"])+" |")
sp={v:float(spearmanr(PL[tgt],ranks[v])[0]) for v in ["V0","V1","V2","V3"]}
def best_chunk_text(q,films):
    s=Cf@q; out={}
    for f in films:
        idxs=np.where(mid==f)[0]; j=idxs[int(torch.argmax(s[torch.tensor(idxs,device=dev)]).item())]; out[f]=txt[j]
    return out
rrp=glob.glob(E+"/hf/hub/models--BAAI--bge-reranker-v2-m3/snapshots/*")[0]
rr=CrossEncoder(rrp,device=dev,max_length=1024,automodel_args={"torch_dtype":torch.float16})
timing={}
Qs={"TR":[b["tr"] for b in B],"EN":[b["en"] for b in B]}
for base in ["V2","V3"]:
    Qv=QT if base=="V2" else QE
    cand={k:torch.topk(SC[(base,k)],50).indices.cpu().numpy() for k in range(50)}
    chunks={k:best_chunk_text(Qv[k],list(cand[k])) for k in range(50)}
    for qlang,qtexts in Qs.items():
        for mode in ["chunk","plot"]:
            r=[]; tms=[]
            for k in range(50):
                top=cand[k]
                docs=[chunks[k][f] for f in top] if mode=="chunk" else [str(df["plot"].iloc[f]) for f in top]
                pairs=[(qtexts[k],d) for d in docs]
                torch.cuda.synchronize(); t=time.time()
                sc=rr.predict(pairs,batch_size=25,show_progress_bar=False); torch.cuda.synchronize(); tms.append(time.time()-t)
                order=top[np.argsort(-sc)]
                if tgt[k] in top: r.append(int(np.where(order==tgt[k])[0][0])+1)
                else: r.append(ranks[base][k])
            nm=f"V4[{base} adaylari, rerank sorgu {qlang}, {mode}]"
            ranks[nm]=r; res+=fmt(nm,r); timing[nm]=float(np.mean(tms[2:]))
    print("rerank done",base,time.time()-t0,flush=True)
base=best; Qv=QT if base=="V2" else QE
top=torch.topk(SC[(base,0)],50).indices.cpu().numpy()
bt=best_chunk_text(Qv[0],list(top)); docs_c=[bt[f] for f in top]; docs_p=[str(df["plot"].iloc[f]) for f in top]
tm={}
rr_cpu=CrossEncoder(rrp,device="cpu",max_length=1024)
for lab,docs in [("chunk",docs_c),("plot",docs_p)]:
    pairs=[(B[0]["tr"],d) for d in docs]
    ts=[]
    for _ in range(2):
        t=time.time(); rr_cpu.predict(pairs,batch_size=10,show_progress_bar=False); ts.append(time.time()-t)
    tm[f"CPU fp32 ({torch.get_num_threads()} thread) 50 aday {lab}"]=float(np.mean(ts))
    ts=[]
    for _ in range(3):
        torch.cuda.synchronize(); t=time.time(); rr.predict(pairs,batch_size=25,show_progress_bar=False); torch.cuda.synchronize(); ts.append(time.time()-t)
    tm[f"GPU fp16 50 aday {lab}"]=float(np.mean(ts))
pickle.dump(dict(ranks=ranks,res=res,tab=tab,sp=sp,tm=tm,timing=timing,best=best),open(E+"/ev2.pkl","wb"))
open(E+"/ev2_tables.md","w",encoding="utf-8").write("\n".join(res)+"\n\n"+"\n".join(tab)+"\n\n"+str(tm)+"\n"+str(timing)+"\n"+str(sp)+"\n")
print("\n".join(res)); print(tm); print(sp); print("toplam",time.time()-t0,flush=True)
CQ=["kimliğini sorgulayan bir kadının psikolojik gerilimi","küçük bir kasabada geçen, yalnızlık ve yas temalı ağır tempolu dram","yapay zekânın insanlarla duygusal bağ kurduğu bilim kurgu","soygun planı ters giden suç komedisi","savaş sonrası travmayla baş eden asker","ıssız bir yerde mahsur kalan bir grup insanın hayatta kalma mücadelesi","çocukluk arkadaşlarının yıllar sonra buluşması, nostalji ve pişmanlık","kasvetli atmosferli, yavaş ilerleyen kuzey ülkesi polisiyesi"]
CE=["a psychological thriller about a woman questioning her identity","a slow-paced drama set in a small town, about loneliness and grief","a science fiction film in which artificial intelligence forms emotional bonds with humans","a crime comedy about a heist plan that goes wrong","a soldier coping with post-war trauma","the survival struggle of a group of people stranded in a deserted place","childhood friends meeting again after many years, nostalgia and regret","a gloomy, slow-burning crime story set in a northern country"]
vt=enc(CQ); ve=enc(CE)
th={}
for qi in range(8):
    th[("tr_single",qi)]=torch.topk(single(vt[qi]),10).indices.cpu().numpy()
    th[("tr_chunk",qi)]=torch.topk(chunk(vt[qi]),10).indices.cpu().numpy()
    th[("en_chunk",qi)]=torch.topk(chunk(ve[qi]),10).indices.cpu().numpy()
    th[("en_single",qi)]=torch.topk(single(ve[qi]),10).indices.cpu().numpy()
nordic=["Norway","Sweden","Denmark","Finland","Iceland"]
cm=df.country.fillna("").apply(lambda s: any(n in [x.strip() for x in s.split(",")] for n in nordic)).values
gm=df.genre.fillna("").str.contains("crime|thriller",case=False).values
fm=torch.tensor(cm&gm,device=dev)
cf={"n_nordic":int(cm.sum()),"n_crime_thriller":int(gm.sum()),"n_both":int((cm&gm).sum())}
for lab,v in [("tr",vt[7]),("en",ve[7])]:
    cf[lab]=torch.topk(chunk(v).masked_fill(~fm,-9),10).indices.cpu().numpy()
    cf[lab+"_single"]=torch.topk(single(v).masked_fill(~fm,-9),10).indices.cpu().numpy()
pickle.dump(dict(th=th,cf=cf,CQ=CQ,CE=CE),open(E+"/th2.pkl","wb"))
print("done")
