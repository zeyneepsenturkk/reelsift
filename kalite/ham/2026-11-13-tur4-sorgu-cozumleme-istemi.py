import os,json,time,urllib.request,urllib.error,re
ENV=".env"
def _env():
    d={}
    for l in open(ENV,encoding="utf-8"):
        for k in ("GEMINI_API_KEY","GEMINI_MODEL","GEMINI_MODELS"):
            if l.startswith(k+"="): d[k]=l.split("=",1)[1].strip().strip('"').strip("'")
    return d
CFG=_env()
MODELS=[CFG["GEMINI_MODEL"]]+[x for x in CFG.get("GEMINI_MODELS","").split(",") if x and x!=CFG["GEMINI_MODEL"]]
PROMPT='''You are the query-understanding component of a movie search engine. The archive's search index is English (Wikipedia plot summaries + TMDB metadata). The user writes in Turkish.
Given the Turkish request below, return ONLY a JSON object with exactly these keys:
{
 "en_query": one English sentence that is a good search query for the request (keep mood/theme/genre/country/period details),
 "hyde": a hypothetical 4-6 sentence English summary of a film that fits the request, written like the "Plot" section of a Wikipedia film article (concrete events, characters; do not mention that it is hypothetical),
 "titles": up to 5 real films that fit the request, [{"title": original/English title, "year": release year as integer}]. If you are not sure a film exists or fits, leave the list empty or shorter. Never invent films,
 "filters": {
   "year_min": integer or null, "year_max": integer or null  (only if the request states or implies a period, e.g. "90s" -> 1990..1999),
   "countries": list of English country names (e.g. "Japan", "South Korea", "United States") or null if no country is requested,
   "genres": list of English genre words (e.g. "horror","comedy","drama") or null if the request names none,
   "max_vote_count": integer or null (set e.g. 2000 only if the user wants lesser-known / obscure films; null otherwise)
 }
}
Set a filter only when the request clearly asks for it; otherwise null. No text outside the JSON.

Turkish request: '''
def call(tr,retries=5):
    last=None
    for mi,model in enumerate(MODELS):
        for a in range(retries):
            body=json.dumps({"contents":[{"parts":[{"text":PROMPT+tr}]}],"generationConfig":{"responseMimeType":"application/json","temperature":0.2}}).encode()
            req=urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",data=body,headers={"Content-Type":"application/json","x-goog-api-key":CFG["GEMINI_API_KEY"]})
            t=time.time()
            try:
                r=json.loads(urllib.request.urlopen(req,timeout=120).read())
                txt="".join(p.get("text","") for p in r["candidates"][0]["content"]["parts"])
                txt=re.sub(r"^```json|```$","",txt.strip()).strip()
                return json.loads(txt),time.time()-t,model,a
            except urllib.error.HTTPError as e:
                last=f"HTTP {e.code}"
                if e.code in (429,500,502,503,504): time.sleep(5*(a+1)); continue
                break
            except Exception as e:
                last=type(e).__name__+": "+str(e)[:100].replace(CFG["GEMINI_API_KEY"],"<k>"); time.sleep(3)
    raise RuntimeError("gemini basarisiz: "+str(last))
if __name__=="__main__":
    o,dt,m,a=call("Başkalarının rüyalarına girip sırlarını çalan bir hırsız, bu kez bir iş adamının zihnine fikir yerleştirmekle görevlendirilir.")
    print(m,a,round(dt,1)); print(json.dumps(o,ensure_ascii=False)[:900])
