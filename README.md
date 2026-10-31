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

Bu komut ağ, API anahtarı ve model olmadan 40 soruluk sabit fikstür izlerini değerlendirme/teşhis akışından geçirir. `naive`, `advanced`, `broken` hatları ve bunların sonuçları **sentetik demonstrasyon fikstürleridir; gerçek Wikipedia arama/üretici performans ölçümü değildir.** Girdi soruları, beklenen yanıtlar ve lisanslı alıntılar `examples/demo/golden.jsonl` içinde; makale revision kimlikleri ve atıflar `examples/demo/SOURCES.md` ile `examples/demo/wiki-mini.revisions.json` içindedir. Makale metni depoya eklenmez.

Sabit revision’lardan yerel demo korpusunu edinmek için (yalnız bu komut ağ kullanır):

```bash
ragnoz demo init
ragnoz run --golden examples/demo/golden.jsonl --adapter examples/demo/adapter.py:build_demo_adapter
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
ragnoz import TRACES.jsonl [--mapping mapping.json] [--output .ragnoz/imported.jsonl]
ragnoz run --golden GOLDEN.jsonl --adapter package.module:factory [--no-cache]
ragnoz eval --golden GOLDEN.jsonl --traces TRACES.jsonl
ragnoz compare --before A.jsonl --after B.jsonl --golden GOLDEN.jsonl
ragnoz diagnose --golden GOLDEN.jsonl --traces TRACES.jsonl [--architecture architecture.yaml]
ragnoz report --golden GOLDEN.jsonl --traces TRACES.jsonl [--redact]
ragnoz experiment run REC-ID --golden GOLDEN.jsonl --before A.jsonl --after B.jsonl
ragnoz experiment run REC-ID --golden GOLDEN.jsonl --adapter package.module:factory
ragnoz ablate --type remove|swap|oracle-context|no-context --module MODULE --adapter package.module:factory --golden GOLDEN.jsonl
```

`experiment run` adapter yolunda `with_experiment(rec_id)` hook’u; `ablate` yolunda `with_ablation(type, module)` hook’u ister. Hook yoksa araç sonucu `inconclusive` bırakır, başarılı deney gibi göstermez. Deney geçiş tablosu, exact McNemar sonucu ve yüzde 95 eşleştirilmiş bootstrap aralığı rapora yazılır. Başarı için önceden belirlenmiş eşiklerin geçilmesi gerekir; aksi halde öneri yüksek güvene yükseltilmez.

İz şeması `question_id`, `answer`, `candidates`, `ranked`, `context`, `route`, `observability` alanlarını destekler. Genel JSONL formatları `--mapping` ile alan eşlemeyi kabul eder. Çevrimdışı `eval` ve `diagnose` sistem adapter’ı olmadan da mevcut izleri okuyabilir.

## Metrikler ve hata atfı

Getirme için aday listesi ve nihai/rerank sonrası liste ayrı raporlanır: `candidate_hit@k`, `hit@k`, `candidate_recall@k`, `recall@k`, `candidate_ndcg@k`, `ndcg@k`, `mrr@k` ve `rerank_gain@k` (`k=1,3,5,10`). Doğruluk ve hit oranlarında Wilson aralığı; eşleştirilmiş farkta bootstrap aralığı ve doğru/yanlış geçişlerde exact McNemar testi kullanılır. `n<30` küçük örneklem uyarısı alır. Cevap kaçınma recall/precision yalnız gold’da reddetme beklenen sorular üzerinden hesaplanır. Sayılar binlik/ondalık ayraç normalizasyonu, tolerans, alt/üst sınır ve birim alanlarını destekler.

Atıf, gözlem seviyesine göre ilk görünür kırılma noktasını işaretler (ör. `RETRIEVAL_MISS`, `RERANK_DROP`, `CONTEXT_DROP`, `GEN_NUMBER_EXTRACTION`, `ABSTAIN_FAIL`, `UNDETERMINED_L0`, `SYS_ERROR`). Anti-pattern motorunda PRD MVP çekirdeği AP-01, AP-02, AP-03, AP-04, AP-05, AP-07, AP-08, AP-09, AP-12, AP-13 ve AP-18 için kural sürümlü tespit bulunur. Kural eşiği/örneklem veya gerekli ablasyon gözlemi yoksa çıkarım yapılmaz.

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

## Lisanslar

RAGnoz kodu kök `LICENSE` dosyasındaki MIT lisansı altındadır. Demo soru/alinti verisi kaynak revision’larına göre CC BY-SA 4.0 koşullarına tabidir; ayrıntı için `examples/demo/SOURCES.md`.
