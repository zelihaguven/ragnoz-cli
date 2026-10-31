# RAGnoz MVP — Uygulama Planı ve Gerçekleşen Kapsam

## Onay ve teslim biçimi

Kullanıcı, tam PRD doğrultusunda **Python tabanlı `ragnoz` CLI MVP**’nin kurulmasını onayladı. Bu teslim web dashboard’u değildir. Yerel-öncelikli, CPU ile çalışan ve gerçek kullanıcı verisini dışarı göndermeyen bir Python paketidir. PRD’nin tamamı tek teslimde uygulanmış gibi gösterilmez: v0.1’de işlevsel çekirdek ve örnek akışlar bulunur; aşağıdaki açık işlerle v0.2+ ayrımı korunur.

## Ürün yaklaşımı

Değerlendirmenin ortak biçimi Pydantic `GoldenItem` ve `QuestionTrace` modelleridir. Girdi yolları YAML/JSONL gold seti, alan eşlemeli genel izler, var olan run izleri ve kullanıcının yazdığı senkron Python adapter’ıdır. Adapter sözleşmesi belge yükleme → chunk → index → retrieve → isteğe bağlı rerank → isteğe bağlı context oluşturma → generate akışını çalıştırır. İçerik adresli stage cache aynı girdi/fingerprint için üst aşama sonuçlarını tekrar kullanır; cache kullanıcı çalışma alanındaki `.ragnoz/` içine yazılır.

Çekirdek değerlendirme, kanıt ve ilk görünür hata noktası üzerinden soru başı atıf üretir; retrieval/rerank öncesi-sonrası ölçümleri, sayısal toleranslar, reddetme ölçümleri, Wilson aralıkları, eşleştirilmiş bootstrap ve exact McNemar çıktıları sağlar. Mimari teşhisi beyan dosyası/adapter `describe()`/izlerden Naive, Advanced veya Modular tanımı ile doğrusal, koşullu, dallanan, döngülü veya bilinmeyen akışı çıkarır. Taksonomi kalite sıralaması değildir. Çekirdek MVP 11 anti-pattern kuralıdır; kalan 8 kural bilinçli olarak tam katalog sürümüne ertelenmiştir.

Her öneri measured evidence ile birlikte hedef modül, eşik, etkilenen soru kimlikleri, hipotez ve deney şablonu taşır. Deney öncesi güven en fazla Orta’dır. A/B yürütme, adapter’ın `with_experiment` hook’una veya dışarıda çalıştırılmış iz çiftlerine dayanır; yalnız iz karşılaştırması nedenselliği kanıtlamaz. Sentetik/demo verisinde geçen deney, gerçek sistem önerisini Yüksek güvene yükseltmez. Ablasyon da yalnız destekli adapter hook’u ya da mevcut sonuç üzerinden inceleme olarak ifade edilir; yapılmamış müdahale başarılı gibi raporlanmaz.

## Demo ve veri politikası

Demo gold seti 40 sorudan oluşur; en az 8 cevapsız soru, sayısal/olgusal, TR↔EN, çok adımlı ve exact-ID örnekleri vardır. `demo run` ve `demo traces` LLM’siz, ağsız, açıkça sentetik fikstürleri işler; bu değerler gerçek retrieval performans kıyası değildir. Naive/Advanced/Broken YAML dosyaları beklenen mimari profilleri açıklar. `demo init`, kullanıcı komutuyla sabit revision ID’lerden yaklaşık 20 Wikipedia sayfasını yerel `.ragnoz/demo-corpus/` içine indirir; metin depoda tutulmaz. Kaynaklar ve CC BY-SA 4.0 atfı manifestte ve indirme klasöründeki `ATTRIBUTION.md` dosyasında yer alır. Demo adapter gerçek fakat basit kelime örtüşmesi retrieval + extractive üretim örneğidir; BM25, dense embedding, reranker veya gelişmiş referans hattı iddiası taşımaz.

Varsayılan çalışma ağsızdır. Tek ağ erişimli yol açıkça çağrılan Wikipedia `demo init` komutudur; retry ve `Retry-After` sınırı vardır. Adapter çağrısı ancak kullanıcı `ragnoz run` yürüttüğünde yapılır. Örnek/gerçek corpus ve cache depoya alınmaz. HTML raporu statik, tek dosyalı ve harici script/font/CDN çağrısı yapmayan biçimdedir; `--redact` cevap ve tanımlayıcı alanlarını maskeler, credential alanları ayrıca süzülür.

## Kullanılan teknoloji ve yapı

Python 3.11+, Typer, Rich, Pydantic v2, PyYAML, Jinja2 ve Wikimedia indirme işlevinde httpx kullanılır. GPU, veritabanı, sunucu veya model hesabı gerekmez. Paket `pyproject.toml` ile dağıtılabilir wheel olarak derlenir; demo manifesti, gold seti, YAML profilleri ve örnek adapter paket içine eklenir.

```text
ragnoz-cli/
├── README.md, LICENSE, plan.md, TODO.md
├── pyproject.toml
├── src/ragnoz/
│   ├── cli.py                     # Typer: demo, golden, import, run/eval/compare/report/diagnose
│   ├── schemas.py                 # Gold, iz, chunk, metrik bulgusu ve öneri tipleri
│   ├── golden.py, corpus.py       # Gold/corpus doğrulama ve sabit revision indirme
│   ├── importers.py               # JSONL içe/dışa aktarma ve alan eşleme
│   ├── adapters/base.py           # Python stage adapter Protocol
│   ├── cache.py, runner.py        # Stage cache ve altı aşamalı yürütücü
│   ├── evaluation/core.py         # Metrikler, sayısal karşılaştırma ve hata atfı
│   ├── compare.py, statistics.py  # Soru geçişleri ve eşleştirilmiş istatistik
│   ├── diagnosis/engine.py        # Mimari keşfi ve 11 çekirdek kural
│   ├── reports/html.py            # Tek dosya çevrimdışı HTML raporu
│   └── data/demo/                 # Pip’e dahil gold set, sabit revision manifesti ve örnek
├── examples/demo/                 # YAML profilleri, kaynak/attribution ve adapter quickstart
└── tests/                         # Şema, metrik, cache, runner, teşhis, demo ve CLI
```

## Geliştirilen ve açık bırakılan yüzeyler

**İşleyen v0.1 yolları:** `demo init|traces|run`; `golden validate`; `import`; adapter ile `run`; `eval`; eşleştirilmiş `compare`; `diagnose`; `report`; hook/iz çifti üzerinden `experiment run`; adapter hook’u üzerinden `ablate`. Run çıktısında iz JSONL, soru bazlı `results.jsonl`, `metrics.json`, `diagnosis.json`, `manifest.json` ve `summary.md` bulunur. Paketlenmiş demo dosyaları wheel içinde kontrol edilmiştir.

**Kapsam sınırları:** yerleşik HTTP POST/GET/black-box adapter’ı yok; kullanıcı Python adapter’ı veya JSONL ile bağlanır. `--only`, `--from-stage`, cache planı/çağrı tahmini ve uzaktan model/judge entegrasyonu yoktur. Tam 19 anti-pattern, YAML kural deposu, gelişmiş probing paketi, tam oracle/no-context müdahale matrisi ve insan etiketleme aracı v0.2+’dır. Compare girdileri aynı CLI çağrısında ortak gold kullanır; run manifestlerinden dataset hash uyuşmazlığı uyarısı henüz tam işlenmez. 11 çekirdek kural kodda sürüm etiketleriyle bulunur; ayrı `rules/` kataloğu yoktur.

## Tasarım sistemi

Bu CLI + rapor ürünü için üç düşük olasılıklı görsel yön: brutalist terminal (0,04); pastel laboratuvar not defteri (0,08); editoryal gözlemlenebilirlik konsolu (0,06). Seçilen yön editoryal gözlemlenebilirlik konsolu.

- **Tasarım hareketi:** Swiss editorial grid ile teknik gözlemlenebilirlik araçlarının ölçülü birleşimi; terminalin taranabilirliği korunur.
- **Temel ilkeler:** Kanıtı iddianın yanına koy; belirsizliği saklama; önce/sonra değişimini belirgin kıl; varsayılanları yapılandırılabilir göster.
- **Renk felsefesi:** Mürekkep laciverti ve kırık beyaz uzun rapor okumayı rahatlatır. Sinyal turuncusu değişiklik/uyarıyı, teal olumlu ölçümü, nötr gri bilinmeyeni gösterir; paradigma renkleri kalite sıralaması ima etmez.
- **Yerleşim paradigması:** CLI’de kısa başlık + hizalı tablo + ayrıntı satırı; HTML’de akış halinde kanıt bölümleri. Gereksiz kart ızgarası yok.
- **İmza öğeleri:** Eşik değerini yanında gösteren ölçüm satırı; değişen/değişmeyen soru kimliklerini taşıyan önce/sonra tablosu; L0–L3 gözlem rozeti.
- **Etkileşim:** CLI seçenekleri açık ve yerel; ağ/adapter eylemleri açıkça bildirilir. HTML raporu tek dosya, çevrimdışı, taşınabilir ve `--redact` uyumlu.
- **Animasyon:** CLI ve raporda animasyon yok; hareket ölçüm okumayı veya erişilebilirliği bozmaz.
- **Tipografi:** Terminalde sabit aralıklı varsayılan font; HTML raporunda sistem sans-serif başlık ve `ui-monospace` ölçüm alanı. Sayılar tabular-nums ile hizalanır.
- **Marka özü:** RAG ekiplerine “hata nerede, kanıt ne, sırada hangi deney var?” sorularını yanıtlayan tarafsız teşhis CLI’si. Kişilik: dürüst, ölçülü, teknik.
- **Marka sesi:** Kısa, ölçülü, kanıt temelli. “Kanıt adaylarda bulundu; modele giden bağlamda yok.” “Bu bir hipotez; Yüksek güven için deneyi çalıştırın.”
- **Wordmark/işaret:** `RAGnoz` logotipi düz tipografik isim; terminal prompt’unda küçük `R/` ölçüm işareti. Ayrı ikon gerekmiyor.
- **İmza rengi:** Sinyal turuncusu `#D97732`; yalnız değişiklik ve eylem vurgusunda.

## Doğrulama durumu

2026-10-20 itibarıyla 29 pytest testi geçmektedir. `mypy` 22 kaynak dosyasında hata bulmamıştır; `ruff` temizdir; şema/cache/evaluation/diagnosis kapsamı %85 eşiğinin üstünde kontrol edilmiştir. Yerel Wikipedia indirmesinde 40/40 alıntı doğrulaması ve gerçek demo adapter `run` akışı çalıştırılmıştır. Bu sonuçlar açık TODO maddelerindeki tüm PRD gereksinimlerinin tamamlandığı anlamına gelmez.
