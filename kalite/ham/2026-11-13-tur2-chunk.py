import re, numpy as np, pandas as pd, pickle, sys
E=sys.argv[1]
df=pd.read_csv(E+"/../dl/final_dataset.csv",low_memory=False)
SPL=re.compile(r'(?<=[.!?])["\')\]]*\s+(?=[A-Z0-9"\'(\[])')
def chunk(text, target=175, lo=150, hi=200, ov=30):
    sents=[s.strip() for s in SPL.split(str(text)) if s.strip()]
    wc=[len(s.split()) for s in sents]
    if sum(wc)<=hi: return [" ".join(sents)]
    out=[]; i=0; n=len(sents)
    while i<n:
        j=i; w=0
        while j<n and (w<lo or (w+wc[j]<=hi)):
            w+=wc[j]; j+=1
            if w>=hi: break
        out.append(" ".join(sents[i:j]))
        if j>=n: break
        # overlap: step back sentences until ~ov words
        k=j; ow=0
        while k>i+1 and ow<ov:
            k-=1; ow+=wc[k]
        i=k if k>i else j
    # merge tiny tail
    if len(out)>1 and len(out[-1].split())<60:
        pass
    return out
if __name__=="__main__":
    mid=[];txt=[]
    for i,t in enumerate(df["plot"].values):
        for c in chunk(t): mid.append(i); txt.append(c)
    L=np.array([len(t.split()) for t in txt])
    print("films",len(df),"chunks",len(txt),"mean words",L.mean(),"p50",np.median(L),"max",L.max(),"total words",L.sum())
    pickle.dump((np.array(mid),txt),open(E+"/chunks.pkl","wb"))
