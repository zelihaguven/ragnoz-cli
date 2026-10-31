# RAGnoz — RAG Hata Atlası

Genel amaçlı, yerel-öncelikli RAG değerlendirme ve mimari teşhis CLI’si. Python 3.11+ ile çalışır; LLM, GPU, veritabanı veya RAG framework bağımlılığı yoktur. Denenen sisteme bağlanmak isteğe bağlı bir Python adapter’ı üzerinden olur.

> Naive / Advanced / Modular etiketleri mimari tanımıdır, kalite puanı değildir. Bir öneri deneyle doğrulanmadıkça yüksek güven taşımaz.

## Kurulum

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
ragnoz --help
```

## İki dakikalık çevrimdışı demo

```bash
ragnoz demo run --pipeline all
```

Bu komut ağ, API anahtarı ve model olmadan 40 soruluk sabit fikstür izlerini değerlendirme/teşhis akışından geçirir. `naive`, `advanced`, `broken` hatları ve bunların sonuçları **sentetik demonstrasyon fikstürleridir; gerçek Wikipedia arama/üretici performans ölçümü değildir.** Girdi soruları, beklenen yanıtlar ve lisanslı alıntılar `src/ragnoz/data/demo/golden.jsonl` içinde; makale revision kimlikleri ve atıflar `src/ragnoz/data/demo/SOURCES.md` ile `src/ragnoz/data/demo/wiki-mini.revisions.json` içindedir. Makale metni depoya eklenmez.

Sabit revision’lardan yerel demo korpusunu edinmek için (yalnız bu komut ağ kullanır):

```bash
ragnoz demo init
ragnoz run --golden src/ragnoz/data/demo/golden.jsonl --adapter src/ragnoz/data/demo/adapter.py:build_demo_adapter
```

`demo init` makale metinlerini `.ragnoz/demo-corpus/` altında tutar. Bu klasör git dışıdır. Wikimedia 429 yanıt verirse araç `Retry-After` başlığını ve artan beklemeyi izler; işlem yarıda kalırsa aynı komut tekrar çalıştırılabilir. Wikipedia metni CC BY-SA 4.0 koşullarına tabidir; CLI indirme klasörüne `ATTRIBUTION.md` yazar.

Wheel kurulumu kullananlar örnek adapter’ı paket modülüyle yükleyebilir: `ragnoz run --golden /path/to/golden.jsonl --adapter ragnoz.data.demo:build_demo_adapter`.

Örnek adapter, yalnız CPU üzerinde çalışan basit kelime örtüşmesi getirme ve extractive üretim hattıdır; BM25, dense embedding veya reranker olduğu iddia edilmez. Üç sentetik demo hattı ise mimari anti-pattern davranışlarını göstermek içindir.

## Kendi sistemini bağlama

`--adapter module:function` veya `--adapter /tam/yol/adapter.py:function` biçiminde, factory tarafından oluşturulan senkron bir nesne verin. Gerekli metodlar:

```python
class MyAdapter:
    def load_documents(self) -> list[dict]: ...
    def chunk(self, documents: list[dict]) -> list[dict]: ...
    def index(self, chunks: list[dict]): ...
    def retrieve(self, question: str, index) -> list[dict]: ...
    def generate(self, question: str, context: list[dict]) -> str | dict: ...
    def describe(self) -> dict: ...
    def fingerprint(self, stage: str): ...
```

`rerank(question, candidates)` ve `build_context(question, ranked)` isteğe bağlıdır; atlanırsa ilgili aşama kimlik dönüşümü yapar. Her iz için `describe()` kaynaklı mimari beyan; `fingerprint(stage)` ise o aşamanın model/sürüm/ayar imzasını dönmelidir. Üretici ayarı değiştiğinde yalnız `generate` fingerprint’i değişirse chunk/index/retrieval/rerank/context cache’leri yeniden kullanılır. Cache ve izler yerel `.ragnoz/` içinde saklanır; adapter’ın dokümanları veya cevapları depoya kopyalanmaz.

Aşama hataları `SYS_ERROR` olarak izlenir; ham hata metni iz dosyasına yazılmaz. `describe()` içine API anahtarı, token, parola veya kimlik bilgisi koymayın. Adapter kendi dış servis çağrılarını yalnız kullanıcı `ragnoz run` komutunu açıkça çalıştırdığında yapar; RAGnoz bunu kendiliğinden yapmaz.

## CLI

```text
ragnoz demo init
ragnoz demo run --pipeline all|naive|advanced|broken
ragnoz golden validate GOLDEN.jsonl [--corpus pages.json]
ragnoz golden quickstart [--from qa.csv|qa.jsonl|qa.md] [--output golden.jsonl] [--corpus pages.json]
ragnoz import TRACES.jsonl [--mapping mapping.json] [--output .ragnoz/imported.jsonl]
ragnoz run --golden GOLDEN.jsonl --adapter package.module:factory [--no-cache]
ragnoz eval --golden GOLDEN.jsonl --traces TRACES.jsonl
ragnoz compare --before A.jsonl --after B.jsonl --golden GOLDEN.jsonl
ragnoz diagnose --golden GOLDEN.jsonl --traces TRACES.jsonl [--architecture architecture.yaml]
ragnoz triage "derdini kendi kelimelerinle anlat" [--golden GOLDEN.jsonl --traces TRACES.jsonl]
ragnoz report --golden GOLDEN.jsonl --traces TRACES.jsonl [--redact]
ragnoz experiment run REC-ID --golden GOLDEN.jsonl --before A.jsonl --after B.jsonl
ragnoz experiment run REC-ID --golden GOLDEN.jsonl --adapter package.module:factory
ragnoz ablate --type remove|swap|oracle-context|no-context --module MODULE --adapter package.module:factory --golden GOLDEN.jsonl
ragnoz inspect adapter.py [--output architecture.draft.yaml]
ragnoz architecture approve architecture.draft.yaml [--output architecture.yaml]
```

Henüz golden set'in yoksa `golden quickstart`, gevşek bir CSV/JSONL/markdown soru-cevap listesini şemaya uygun bir `golden.jsonl`'a çevirir ve otomatik olarak `golden validate` çalıştırır; eksik/bozuk satırları satır numarasıyla bildirir. Derdini "elindeki golden set" veya "rule id" dilinde değil, kendi kelimelerinle anlatmak istiyorsan `triage` kullanılır — aşağıdaki örneklere bakın.

`experiment run` adapter yolunda `with_experiment(rec_id)` hook’u; `ablate` yolunda `with_ablation(type, module)` hook’u ister. Hook yoksa araç sonucu `inconclusive` bırakır, başarılı deney gibi göstermez. Deney geçiş tablosu, exact McNemar sonucu ve yüzde 95 eşleştirilmiş bootstrap aralığı rapora yazılır. Başarı için önceden belirlenmiş eşiklerin geçilmesi gerekir; aksi halde öneri yüksek güvene yükseltilmez.

İz şeması `question_id`, `answer`, `candidates`, `ranked`, `context`, `route`, `observability` alanlarını destekler. Genel JSONL formatları `--mapping` ile alan eşlemeyi kabul eder. Çevrimdışı `eval` ve `diagnose` sistem adapter’ı olmadan da mevcut izleri okuyabilir.

## Metrikler ve hata atfı

Getirme için aday listesi ve nihai/rerank sonrası liste ayrı raporlanır: `candidate_hit@k`, `hit@k`, `candidate_recall@k`, `recall@k`, `candidate_ndcg@k`, `ndcg@k`, `mrr@k` ve `rerank_gain@k` (`k=1,3,5,10`). Doğruluk ve hit oranlarında Wilson aralığı; eşleştirilmiş farkta bootstrap aralığı ve doğru/yanlış geçişlerde exact McNemar testi kullanılır. `n<30` küçük örneklem uyarısı alır. Cevap kaçınma recall/precision yalnız gold’da reddetme beklenen sorular üzerinden hesaplanır. Sayılar binlik/ondalık ayraç normalizasyonu, tolerans, alt/üst sınır ve birim alanlarını destekler.

Atıf, gözlem seviyesine göre ilk görünür kırılma noktasını işaretler (ör. `RETRIEVAL_MISS`, `RERANK_DROP`, `CONTEXT_DROP`, `GEN_NUMBER_EXTRACTION`, `ABSTAIN_FAIL`, `UNDETERMINED_L0`, `SYS_ERROR`). Anti-pattern motorunda PRD MVP çekirdeği AP-01, AP-02, AP-03, AP-04, AP-05, AP-07, AP-08, AP-09, AP-12, AP-13 ve AP-18 için kural sürümlü tespit bulunur. Kural eşiği/örneklem veya gerekli ablasyon gözlemi yoksa çıkarım yapılmaz.

## Örnek çıktı: diagnose ve triage

Aşağıdaki çıktılar gerçek komut çalıştırmalarından alınmıştır (demo fikstürleri üzerinde `ragnoz demo traces` ile üretilmiş `broken` iz dosyası kullanılmıştır — bu nedenle sentetiktir, canlı sistem ölçümü değildir).

### `ragnoz diagnose` — tam, ölçülmüş teşhis

```text
$ ragnoz diagnose --golden src/ragnoz/data/demo/golden.jsonl --traces .ragnoz/demo-traces/broken.jsonl \
    --architecture src/ragnoz/data/demo/pipelines/broken.yaml

Mimari: Naive · akış: linear · gözlem: L3
Bulgular: 4 · öneriler: 4
AP-05 Reddetme mekanizması yok / zayıf — cevapsız soru 8/8 reddedilmedi (eşik ≥5 cevapsız soru ve reddetme duyarlılığı <0.5)
AP-01 Parça × top_k bağlam bütçesini aşıyor — 1024×12=12288 token; pencere bütçesi=7372 (eşik parça×top_k ≤0.9×8192)
AP-04 top_k yüksek: dikkat dağılması olasılığı — top_k=12; bağlam kanıtlı yanlış=5 (eşik top_k≥10 ve ≥5 kanıtlı yanlış)
AP-07 Soru ve belge dili uyumsuzluğu olabilir — aday hit en=0.00, tr=0.50 (eşik dil farkı ≥0.20; grup başına ≥10)
rec-001  generation: Reddetme kuralı ve yapılandırılmış bulunamadı yanıtı ekleyin.
rec-002  context: Parça boyutunu veya top_k'yı düşürüp truncation oranını ölçün.
rec-003  post_retrieval.context: top_k=3/5/10 taraması yapın; sonucu ayrı doğrulama sorularında teyit edin.
rec-004  retrieval.embedding: Çok dilli gömme modeli veya BM25 hibrit kolunu deneyin.
Tanı dosyası: .ragnoz/diagnosis.json
```

Her bulgu ve öneri ölçülmüş bir değer (`measured`), bir eşik (`threshold`) ve bir güven derecesi taşır; `diagnosis.json` içinde ayrıca `cannot_infer` listesi hangi iddiaların bu veriden çıkarılamayacağını açıkça sayar.

### `ragnoz triage` — veri yokken (yalnız yönlendirme, bulgu DEĞİL)

```text
$ ragnoz triage "cevaplar alakasız geliyor"

╭──── Yönlendirme (ölçülmüş bulgu DEĞİL — ne yapman gerektiğini söylemez) ─────╮
│ Cevaplar alakasız / tutarsız geliyor                                         │
│   Bak: indexing.chunking, post_retrieval, post_retrieval.context,            │
│ retrieval.embedding  ·  kurallar: AP-02, AP-03, AP-04, AP-07                 │
│   Sıradaki adım: ragnoz golden quickstart --from qa.csv (en az 5-10          │
│ soru-cevap)                                                                  │
╰──────────────── Gerçek, kanıtlı teşhis için: ragnoz diagnose ────────────────╯
```

Golden set ve iz dosyan yoksa `triage` sana sadece **nereye bakman gerektiğini** (modül adı, ilgili kural kimlikleri, sıradaki komut) söyler. `Guidance` tipi yapısal olarak bir düzeltme/öneri alanı taşıyamaz — bu ayrım tip seviyesinde zorlanır, metinle değil.

### `ragnoz triage` — veri varken (gerçek diagnose çıktısından filtrelenmiş)

```text
$ ragnoz triage "cevaplar alakasız geliyor" --golden src/ragnoz/data/demo/golden.jsonl \
    --traces .ragnoz/demo-traces/broken.jsonl --architecture src/ragnoz/data/demo/pipelines/broken.yaml

Eşleşen semptom(lar): irrelevant_answer
Bu şikayetle ilişkili, ölçülmüş bulgular (tam diagnose çıktısından filtrelendi):
  AP-04 top_k yüksek: dikkat dağılması olasılığı — top_k=12; bağlam kanıtlı yanlış=5 (eşik top_k≥10 ve ≥5 kanıtlı yanlış)
  AP-07 Soru ve belge dili uyumsuzluğu olabilir — aday hit en=0.00, tr=0.50 (eşik dil farkı ≥0.20; grup başına ≥10)
  → rec-003  post_retrieval.context: top_k=3/5/10 taraması yapın; sonucu ayrı doğrulama sorularında teyit edin.
  → rec-004  retrieval.embedding: Çok dilli gömme modeli veya BM25 hibrit kolunu deneyin.
```

Golden set ve iz dosyan varsa `triage` artık tahmin etmez: tam `ragnoz diagnose` çıktısını üretir ve şikayetinle eşleşen semptomların kuralları (`rules_by_symptom`) ile bulgu/öneri listesini filtreler. `AP-05` ve `AP-01` gibi şikayetle ilgisiz bulgular listeden düşer; hiçbiri uydurulmaz, hepsi `diagnose`'un ürettiği ölçülmüş kümenin bir alt kümesidir.

## Mimariyi kodundan çıkarma: inspect ve onay

Elle bir `architecture.yaml` yazmak istemiyorsan, `ragnoz inspect` adapter dosyanı statik olarak tarar. Tek kuralı şudur: **ne BULDUĞUNU söyler, ne ÇIKARDIĞINI söylemez.** Bilinen anahtar kelimeler (`top_k`, `chunk_size`, ...), importlar (`faiss`, `sentence_transformers`, ...) ve opsiyonel metod tanımları (`rerank`, `build_context`) için yalnız dosya+satır kanıtlı, ham bulgular üretir — mimari veya kalite hakkında hiçbir yorum yapmaz.

```text
$ ragnoz inspect my_adapter.py --output architecture.draft.yaml

4 bulgu bulundu (dosya+satır kanıtlı): architecture.draft.yaml
  my_adapter.py:1  indexing.import = faiss
  my_adapter.py:6  retrieval.top_k = 8
  my_adapter.py:6  indexing.chunking.chunk_size = 512
  my_adapter.py:11  post_retrieval.rerank.method_present = rerank
Bu bir TASLAKTIR, ölçülmüş girdi değil. Onaylamak için: ragnoz architecture approve architecture.draft.yaml --output architecture.yaml
```

Çıkan `architecture.draft.yaml` dosyası `inspected_draft: true` işaretini taşır. `diagnose`/`triage`/`report` bu işareti gördüğünde **çalışmayı reddeder** — taslak hiçbir şekilde sessizce ölçülmüş girdi sayılamaz, bu tip seviyesinde zorlanan bir kuraldır, sadece bir dosya adı kuralı değildir:

```text
$ ragnoz diagnose --golden GOLDEN.jsonl --traces TRACES.jsonl --architecture architecture.draft.yaml

Mimari dosyası kullanılamadı: architecture.draft.yaml bir inspect taslağıdır (ölçülmüş girdi değil). Önce onaylayın: ragnoz architecture approve <taslak> --output architecture.yaml
```

Taslağı gözden geçirip onaylamak — yani bulguların artık güvenilir bir beyan olduğuna karar vermek — kullanıcının açık eylemidir:

```text
$ ragnoz architecture approve architecture.draft.yaml --output architecture.yaml

Onaylandı: architecture.draft.yaml → architecture.yaml
Bundan sonra bu dosyadaki alanlar `ragnoz diagnose --architecture` için yüksek güvenli beyan sayılır.
  modules.indexing.chunking: {'import': 'faiss', 'chunk_size': '512'}
  modules.retrieval.retriever: {'top_k': '8'}
  modules.post_retrieval.reranker: {'method_present': 'rerank'}
```

`ragnoz diagnose --architecture architecture.yaml` artık bu alanları `source: declaration, confidence: high` olarak kullanır — tam olarak elle yazılmış bir mimari beyanı gibi. Onay adımını atlamak mümkün değildir; `diagnose` taslağı doğrudan verirse hata verir.

## Çıktılar ve gizlilik

- `.ragnoz/`: yerel cache, `traces.jsonl`, soru bazlı `results.jsonl`, `metrics.json`, `diagnosis.json`, `summary.md` ve deney çıktıları; git dışı.
- `report`: harici font, script veya CDN gerektirmeyen tek dosyalı HTML. `--redact` cevap/gerekçe metinlerini ve tanımlayıcıları maskeler; credential anahtar/değer desenleri redaksiyondan bağımsız gizlenir.
- Uzak URL, kimlik bilgisi, gerçek kullanıcı soru dağılımı, modelin fine-tune durumu, düşük gözlemli gizli modüller ve müdahale olmadan nedensellik tahmin edilmez.

## Bilinen MVP sınırları

- Yerleşik HTTP/POST/GET, OpenTelemetry, Langfuse veya framework adapter’ı yoktur; Python `module:function` sözleşmesi ve genel JSONL içe aktarma kullanılabilir.
- Aşama cache’i fingerprint bazlıdır; `--only`, `--from-stage` ve cache hit planlama CLI bayrakları MVP’ye dahil değildir.
- Demo fikstürleri gerçek referans motor kıyaslaması değildir. Wikipedia içerik indirme ve canlı demo adapter’ı yalnız `demo init` sonrasında kullanılabilir.
- Ablation/A-B’nin canlı sistemde çalışması adapter hook’larına bağlıdır. Yalnız trace karşılaştırması yapılabiliyorsa CLI bunu dış çalıştırılmış A/B olarak ele alır; causal iddia üretmez.
- PRD’nin tam 19 anti-pattern kataloğu, LLM-yargıç kalibrasyonu, geniş probing/arama ve paylaşılabilir web arayüzü v0.2+ kapsamıdır. `visual_agent` yalnız opsiyonel bir vaka çalışmasıdır ve varsayılan bağımlılık değildir.
- `inspect` yalnız sabit bir anahtar kelime/import/metod-adı listesiyle AST üzerinde desen eşler; dinamik olarak oluşturulan config (ör. bir ortam değişkeninden okunan `top_k`) veya tanınmayan isimler bulunamaz ve sessizce atlanır — bu durumda mimari bilinmiyor olarak kalır, yanlış tahmin edilmez.

## Lisanslar

RAGnoz kodu kök `LICENSE` dosyasındaki MIT lisansı altındadır. Demo soru/alinti verisi kaynak revision’larına göre CC BY-SA 4.0 koşullarına tabidir; ayrıntı için `src/ragnoz/data/demo/SOURCES.md`.
