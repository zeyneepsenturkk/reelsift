# Yerel model, uygulama içi deneme (2026-11-24)

Ortam: ayrı bir backend konteyneri (`SEARCH_WARMUP=0`, `LLM_PROVIDER=ollama`), host'ta Ollama 0.35.0, model `qwen3:4b-instruct-2507-q4_K_M`, `num_ctx` 12288, RTX 4060. Uygulamanın kendi sağlayıcı sınıfı (`OllamaLLM`, `apps/agent/services/llm_ollama.py`) `build_llm()` üzerinden çağrıldı: bir yapılı çıktı çağrısı (`AltQueryOutput`, anlama adımı) ve bir akışlı cevap çağrısı.

Sonuç: ikisi de çalıştı. Yapılı çıktı 11,0 sn (ilk çağrı, model yükleme dahil; giriş 112, çıkış 31 token). Akışlı cevap 1,1 sn, ilk parça 0,1 sn, 72 parça (giriş 46, çıkış 73 token).

Ham çıktı:

```
sinif OllamaLLM qwen3:4b-instruct-2507-q4_K_M 12288 http://host.docker.internal:11434
2026-11-24 20:28:36,878 INFO httpx2 HTTP Request: POST http://host.docker.internal:11434/api/chat "HTTP/1.1 200 OK"
2026-11-24 20:28:36,880 INFO apps.agent.services.llm_ollama llm step=parse model=qwen3:4b-instruct-2507-q4_K_M in=112 out=31 stop=stop seconds=11.0
STRUCTURED sn=11.0
AltQueryOutput(en_query='slow, melancholic Turkish films about migration', hyde='melancholic Turkish films on migration, slow pace')
2026-11-24 20:28:36,945 INFO httpx2 HTTP Request: POST http://host.docker.internal:11434/api/chat "HTTP/1.1 200 OK"
2026-11-24 20:28:37,967 INFO apps.agent.services.llm_ollama llm step=chat model=qwen3:4b-instruct-2507-q4_K_M in=46 out=73 stop=stop seconds=1.1
STREAM sn=1.1 ilk_parca=0.1 parca=72
```
