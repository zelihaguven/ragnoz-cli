# RAGnoz MVP — Teslim Durumu

> Maddeler PRD v0.2 kabul koşullarını izler. Bu sürümde 11 çekirdek anti-pattern uygulanır; tam katalog ve aşağıdaki tamamlanmamış ölçütler v0.2+ için açık kalır. Alt işlerin bir kısmı çalışır olsa bile ilgili başlık tüm kabul koşulları tamamlanmadan `[ ]` olarak kalır.

## Kanıtlanmış ilerleme

- [x] Python 3.11+ Typer CLI, Pydantic şemalar, JSONL/YAML gold set, genel JSONL import/mapping, Python stage adapter ve yerel fingerprint cache mevcut.
- [x] Ölçüm çekirdeği, sayısal toleranslar, atıf, mimari sınıflandırma/uyuşmazlık, 11 anti-pattern, ölçüme dayalı öneriler ve tek dosya çevrimdışı HTML raporu mevcut.
- [x] 40 soruluk gold set, sabit revision manifesti, üç sentetik tanıtım profili ve basit gerçek Wikipedia demo adapter’ı mevcut; içerik depoya eklenmez.
- [x] `demo init` ile yerel public corpus alındı; `golden validate` 40/40 kaydı doğruladı ve 40 soruluk adapter run’ı yazdı.
- [x] Wheel paketinde demo gold seti, sabit revision manifesti, pipeline YAML ve örnek adapter dosyalarının bulunduğu doğrulandı.
- [x] Anti-pattern kuralları koddan YAML kataloğuna taşındı (`src/ragnoz/data/rules/*.yaml`); `rules_by_symptom()` ters indeksi `triage`'ın temelini oluşturur.
- [x] `ragnoz golden quickstart`: gevşek CSV/JSONL/markdown soru-cevap listesini şemalı `golden.jsonl`'a çevirir, otomatik `golden validate` çalıştırır, satır numaralı hata raporu verir.
- [x] `ragnoz triage "şikayet"`: doğal dil şikayeti semptomlarla eşleştirir; golden+traces yoksa yalnız yönlendirme (`Guidance`, düzeltme önerisi taşıyamaz — tip seviyesinde zorlanır), varsa gerçek `diagnose` çıktısını filtreler.
- [x] `ragnoz inspect` + `ragnoz architecture approve`: adapter kaynağını statik AST taramasıyla dosya+satır kanıtlı bir TASLAK (`architecture.draft.yaml`) üretir; `diagnose`/`triage`/`report` onaysız taslağı ölçülmüş girdi saymaz ve reddeder (yapısal kontrol, dosya adı kuralı değil).
- [x] `cli.py` (575 satır) stage bazlı alt modüllere bölündü (`src/ragnoz/cli/{demo,golden,pipeline,diagnosis,experiment,architecture}.py`); davranış değişmedi, `ragnoz.cli:app` giriş noktası aynı.
- [x] Son doğrulama (2026-10-31, bu depoda çalıştırılarak alındı — uydurma değil): **126 pytest testi, tümü geçiyor**; satır kapsamı **%90** (`src/ragnoz/data/demo/adapter.py` veri dosyası dahil — bkz. madde 5); `ruff check .` → "All checks passed"; `mypy src` → "Success: no issues found in 34 source files" (`types-PyYAML` stub paketi kurulduktan sonra).

## Açık kapsam notları

- Yerleşik HTTP/POST/GET veya kapalı-kutu probing adapter’ı yok; entegrasyon JSONL ya da kullanıcı Python adapter’ıyla yapılır.
- Stage cache için `--only`, `--from-stage`, çağrı planı/istatistik kartı yok; cache’in baştan kurulabilirliği ve kapsamı mevcut fakat tüm PRD kontrol bayrakları değil.
- Ablation için tam 2×2 oracle/no-context yürütme yok; gerçek A/B/ablation adapter hook’una bağlı. Yalnız sentetik demo iziyle deney sonucu yüksek güvene çıkamaz.
- Tam 19 YAML anti-pattern kataloğu değil, PRD MVP’sinin 11 çekirdek kuralı kodda bulunur; kalan 8 kural ertelenmiştir.
- Her CLI gereksiniminin tamamlandığı iddia edilmez; takip eden bölümlerdeki `[ ]` başlıkları açık kabul maddeleridir.

- [ ] **Altın set, kanonik iz ve içe aktarma**
  - Durum: Pydantic alanlarının tamamı (`id`…`provenance`), `golden validate`, genel JSONL `import` + `--mapping`, Python `module:function` adapter ve aşama Protocol'leri çalışır ve testli. Açık kalan: HTTP POST/GET adapter/istek-yanıt eşleme ve zaman aşımı/yeniden deneme hiç yok.
  - Altın set YAML veya JSONL olarak okunmalı; her kayıt Pydantic modeliyle doğrulanmalı.
  - Her kayıt `id`, `question`, `lang`, `type` (factual, numeric, unanswerable, multi_hop, ambiguous, procedural), `tags`, `expected_behavior` (answer / abstain / clarify), `expected_answer`, `expected_values`, `must_include`, `must_not_include`, `evidence[]` (doc_id, sayfa, isteğe bağlı karakter aralığı ve alıntı), `evidence_mode` (any / all), `forbid_docs`, `clarify_options` ve `provenance` alanlarını desteklemeli.
  - `golden validate`: şema, yinelenen ID, korpusta olmayan doc_id, korpus metninde olmayan kanıt alıntısı ve belirsiz sayfa numarası esasını raporlamalı. Golden set özeti her run manifestinde yer almalı; golden/corpus özeti değişince karşılaştırma uyarı vermeli.
  - Genel RAGnoz JSONL izi ve `question_id` veya `question`, `retrieved_chunks[]`, `answer` asgari alanlarını içeren izler değerlendirilip atfedilmeli; alan eşleme biçimi desteklenmeli; eksik iz alanları hata yerine gözlem seviyesini düşürmeli.
  - Başka biçimde soru listelerini alan eşleme dosyasıyla içe aktarma; HTTP POST/GET, istek/yanıt eşleme, zaman aşımı/yeniden deneme; Python `module:function` uçtan uca adaptörü ve aşama Protocol’leri (chunker, retriever, reranker, context builder, generator) bulunmalı. Aşamalar atlanabilmeli. Bu ortamda kullanılabilir her yol yerel, güvenli varsayılanlarla çalışmalı.

- [ ] **Değerlendirme, hata atfı ve reddetme/netleştirme**
  - Durum: `hit@k`/`recall@k`/`mrr@k`/`ndcg@k`/`rerank_gain@k` (k=1,3,5,10, aday vs son liste ayrı), sayısal tolerans/aralık/ayraç/birim, `GOLDEN_INVALID`/`UNDETERMINED_L0`/`SYS_ERROR` atıf kodları ve kural tabanlı yargıç çalışır ve testli. Açık kalan: LLM-yargıç (isteğe bağlı yol) hiç implemente edilmedi — yalnız kural tabanlı yargıç var.
  - Her soru için tam bir birincil hata sınıfı, ikincil etiketler ve insanın okuyabileceği gerekçe verilmeli; iz seviyesi L0–L3 iddiaları sınırlandırmalı.
  - Getirme metrikleri yapılandırılabilir k değerleri (varsayılan 1, 3, 5, 10) ile hit@k, recall@k, MRR ve nDCG@k olmalı; rerank öncesi aday ve sonrası liste ayrı ölçülmeli ve rerank kazancı hesaplanmalı.
  - Sayısal eşleşme aralık, ± tolerans, alt/üst sınır, TR/EN ondalık/binlik ayracı ve birimleri desteklemeli; cevap sayıları beklenen, bağlamda olan çeldirici veya bağlamda olmayan uydurma olarak sınıflanmalı.
  - Reddetme ve netleştirme değerlendirmesi bulunmalı. Kural tabanlı yargıç varsayılan; LLM-yargıç ancak açık ve isteğe bağlı, insan kalibrasyon ölçümleriyle işaretli olmalı.
  - Altın kanıt geçersizse `GOLDEN_INVALID`; L0’da aşama ayrımı desteklenmiyorsa `UNDETERMINED_L0`; doğru kanıtı getirme/aday/rerank/son bağlam aşamalarına göre ilk kırılma noktasına atanmalı. Tek soru hatası tüm run’ı durdurmamalı; `SYS_ERROR` olarak kaydedilmeli.

- [ ] **Önbellekli çalıştırıcı ve tekrarlanabilirlik**
  - Durum: İçerik adresli fingerprint cache (`cache.py`) ve `--no-cache` çalışır ve testli. Açık kalan: `--only`, `--from-stage`, `--plan`/çağrı sayısı önizlemesi hiç yok (`ragnoz run --help` bunları göstermiyor); bayt-düzeyinde tekrarlanabilirlik ve seed aktarımı ayrıca doğrulanmadı.
  - Altı kanonik aşama: parçala → indeksle → getir → yeniden sırala → bağlam kur → üret; değişmeyen üst aşamalar içerik adresli önbellekten gelmeli, yalnız değişen aşama ve aşağısı çalışmalı.
  - Aşama denetimi için `--only`, `--from-stage`, `--no-cache`; yarım run önbellekten sürdürme; --plan desteği varsa hangi aşamaların cache’ten geleceğini ve çağrı sayısını göstermeli.
  - Yalnız üretici yapılandırması/istem değiştiğinde getirme tarafı cache isabeti %100 olmalı; değerlendirme-yalnız değişiklik demo setinde ≤10 saniye ve sıfır model çağrısı hedeflemeli.
  - Aynı manifestten önbellekle üretilen `results.jsonl` bayt düzeyinde aynı olmalı. Tohum (seed) stokastik aşamalara aktarılmalı; desteklemeyen aşama nondeterministic olarak işaretlenmeli.
  - Canlı ve çevrimdışı demo izleri aynı soru bazlı sonuçları ve hata sınıflarını vermeli.

- [ ] **Karşılaştırma, metrik dürüstlüğü ve raporlama**
  - Durum: `compare` Wilson/bootstrap/McNemar kullanır ve testli; `results.jsonl`/`metrics.json`/`summary.md` ve tek dosyalı `--redact` destekli HTML rapor çalışır ve testli. Açık kalan: golden/corpus hash farkında "elma–armut" uyarısı ve `n<30` küçük örneklem uyarısının compare çıktısında açıkça göründüğü ayrıca doğrulanmadı.
  - `compare A B`: metrik farkları, soru bazlı geçiş matrisi, hata sınıfı geçişleri, düzelen/bozulan/değişmeyen soru kimlikleri ve yapılandırma farkını göstermeli.
  - Her compare’de önce/sonra soru tablosu ilk tablo olmalı. Golden/corpus hash farkları “elma–armut” karşılaştırma uyarısı üretmeli.
  - Oranlar Wilson güven aralığıyla, eşleştirilmiş farklar bootstrap aralığıyla, doğru/yanlış eşleşmeleri exact McNemar testiyle sunulmalı. Her oran yanında `n`; `n < 30` için küçük örneklem uyarısı olmalı.
  - Terminal ve paylaşılabilir, harici kaynak yüklemeyen tek dosya statik HTML raporu olmalı. Makinece okunur `results.jsonl`, `metrics.json`, `summary.md` üretimi ve rapordaki `--redact` maskesi desteklenmeli.

- [ ] **Mimari keşif, sınıflandırma ve anti-pattern teşhisi**
  - Durum: Beyan–gözlem çelişkisi (`DECL_MISMATCH`), paradigma/akış sınıflandırması, versiyonlu 11 çekirdek kural (artık `data/rules/*.yaml` kataloğunda, kodda gömülü değil) ve `cannot_infer` kutusu çalışır ve testli. `ragnoz inspect`/`architecture approve` ile statik kod taramasından kanıtlı beyan üretimi de bu dönemde eklendi. Açık kalan: kara kutu yoklaması (black-box probing) hiç yok, PRD'de de P1/kısmi olarak işaretli.
  - Mimari keşif beyan dosyası, adaptör `describe()`, iz çıkarımı kaynaklarından; her mimari gerçeğin kaynağı ve güveniyle yapılmalı. Kara kutu yoklaması MVP’de kısmi/P1 olarak etiketlenmeli.
  - Beyan ile gözlem çelişkisi bulgu olmalı (ör. reranker beyanlı, aday ve son liste izlerde aynı). Paradigma Naive / Advanced / Modular, akış doğrusal / koşullu / dallanan / döngülü olarak sınıflandırılmalı; tetikleyen kural ve modül/operatör envanteri görünmeli. “Modular daha iyi” sonucu çıkarılmamalı.
  - MVP kural dosyaları sürümlü olmalı ve çekirdek 11 kuralı içermeli: AP-01, AP-02, AP-03, AP-04, AP-05, AP-07, AP-08, AP-09, AP-12, AP-13, AP-18. Her kurala asgari örneklem/gözlem seviyesi, kanıt, eşik ve öneri/deney şablonu bağlanmalı. Eksik gözlemde sessizce tahmin değil “değerlendirilemedi” raporlanmalı.
  - Teşhis raporu mimari profili, deklarasyon–iz uyuşmazlıkları, bulguların ölçülen değeri/eşiği/soru ID’leri, öneriler, ablasyon özeti ve “Bu sonuçtan çıkarılamayanlar” kutusunu içermeli.

- [ ] **Öneri yaşam döngüsü, A/B ve ablasyon**
  - Durum: `Recommendation` şeması (hedef modül, bulgu/metrik/n/CI/soru ID, hipotez, değişiklik, alternatif, güven gerekçesi, maliyet/risk, deney, `cannot_infer`) ve `experiment run`/`ablate --remove|swap|oracle-context|no-context` çalışır ve testli. `config-diff` tipi de `ablate --help`'te mevcut. Açık kalan: offline/black-box yol için `config_diff` çıkışının "doğrulanmadı" etiketiyle döndüğü ayrıca uçtan uca doğrulanmadı.
  - Hiçbir öneri ölçülmüş bulgu olmadan oluşturulamaz. Her öneri hedef modül, bulgu/metrik/n/CI/soru ID’leri, hipotez, değişiklik ve alternatifler, kullanıcının verisinden etki tavanı, güven gerekçesi, maliyet/risk, doğrulama deneyi ve kapsam sınırını taşımalı.
  - Öneri dili “X modülü, Y ölçümü nedeniyle geliştirilebilir; Z’yi deneyin” biçiminde olmalı. Deney öncesi güven en fazla Orta; yüksek güven ancak ilgili A/B veya ablasyon başarılı olduktan sonra verilmeli. Kara kutu/L0 ipuçları düşük güvenli kalmalı.
  - `experiment run <rec-id>` öneriyi tek değişkenli yapılandırma farkı olarak çalıştırmalı, cache’i kullanmalı, compare raporunu iliştirmeli ve sonucu verified / refuted / inconclusive durumuna çekmeli. Offline/black-box için çalıştırma mümkün değilse `config_diff` vermeli, doğrulanma iddiası olmamalı.
  - `ablate --remove`, `--swap`, `--oracle-context`, `--no-context` temel türleri bulunmalı; kâhin bağlam mevcut/doğru ve kâhin yanlış/mevcut yanlış 2×2 yorumunu desteklemeli. “Gereksiz karmaşıklık” önerisi doğruluk farkı yokluğu ve ölçülmüş maliyet/gecikme ile ilişkilendirilmeli.

- [ ] **Wikipedia demo korpusu ve hızlı başlangıç**
  - Durum: `demo init`/`demo traces`/`demo run --pipeline naive|advanced|broken|all` ağsız çalışır ve testli; naive/advanced/broken profilleri PRD'deki parametrelerle tohumlanmış. `examples/demo/` kaldırıldı — `src/ragnoz/data/demo/` artık tek kaynak (40 soruluk golden.jsonl, 20 revision'lık manifesto doğrulandı: bkz. madde 4). Açık kalan: yok.
  - Sabit revizyon kimlikleriyle yaklaşık 20 Wikipedia makalesi (Türkçe/İngilizce ve paralel konular) `demo init` sırasında MediaWiki API’den indirilmeli; makale metni depoya eklenmemeli. Başlık, revision bağlantısı ve CC BY-SA 4.0 atfı `ATTRIBUTION.md`/`SOURCES.md` içine yazılmalı.
  - Elle doğrulanmış yaklaşık 40 soruluk demo gold seti; en az 8 cevapsız, sayısal, olgusal, TR soru→EN belge, çok adımlı ve tam kimlikli örnekler içermeli.
  - Naive hattı 512 token sabit parça, BM25 top-5, extractive üretim ve reddetme yok; advanced hattı başlık tabanlı parçalama, BM25+dense+RRF, reranker, top-5 ve eşikli reddetme; broken hattı 1024 token parça, yalnız İngilizce embedding profili, top-12, reddetme yok ve 8K bağlam profiliyle AP-01/04/05/07 tohumlanmış örnek olmalı.
  - Varsayılan demo LLM’siz ve GPU’suz olmalı. `src/ragnoz/data/demo/` (pakete dahil, tek kaynak) altındaki hazır izlerle ağsız demo/diagnose çalışmalı. `demo run`, rapor, diagnose, experiment ve ablation üzerinden örnek uçtan uca hikâye gösterilmeli.

- [ ] **MVP teslim kabulü (PRD §3.3)**
  - Durum: Listelenen tüm komutlar (`golden validate/quickstart`, `run`, `import`, `eval`, `compare`, `report`, `diagnose`, `experiment run`, `triage`, `inspect`, `architecture approve`) çalışır ve testli; satır kapsamı ≥%85 hedefi aşıldı (%90, bkz. madde 1). Açık kalan: cache hit %100 garantisi, sentetik hata enjeksiyonunun `GEN_NUMBER_EXTRACTION`'a doğru atandığı ve canlı/offline iz eşdeğerliği bu oturumda ayrıca uçtan uca yeniden doğrulanmadı (önceki fazlarda doğrulanmıştı, bu çalışma onları değiştirmedi).
  - `golden validate`, `run`, `import`, `eval`, `compare`, `report` komutları çalışır ve testli olmalı.
  - `diagnose` ve `experiment run` komutları çalışır ve testli olmalı.
  - Kamuya açık demo korpusu, örnek gold set ve üç referans hat uçtan uca depoda yer almalı; demo LLM kurulmadan çalışmalı.
  - Aynı demo hattının canlı çalıştırması ile dışa aktarılan izlerin offline içe aktarımı aynı soru bazlı sonuçları ve hata sınıflarını vermeli.
  - Yalnız istem değişince retrieval/rerank cache hit %100 olmalı.
  - Sentetik hata enjeksiyonunda (bağlamdaki doğru sayı yerine yanlış sayı üreten üretici) `GEN_NUMBER_EXTRACTION` doğru atanmalı.
  - Teşhis motoru demo hatlarının paradigmasını doğru sınıflandırmalı; broken hatta tohumlanmış AP’leri yakalamalı; her öneri kanıt, güven ve deney taşımalı.
  - Şema, cache, atıf, metrik ve teşhis çekirdek testlerinde ≥%85 satır kapsamı hedeflenmeli.

- [ ] **Gizlilik, taşınabilirlik ve bakım**
  - Durum: `.ragnoz/` git dışı, `--redact` çalışır ve testli, Python 3.11+ hedefleniyor. Açık kalan: CI henüz yoktu (bu oturumda madde 3'te kuruluyor), performans hedefleri (≤10sn/≤30sn) ve macOS/Windows/Linux üçlü platform testi hiç ölçülmedi/doğrulanmadı.
  - Varsayılan çalışma ağsız; kullanıcı korpusu ve altın set kendi klasöründe kalmalı, depoya/örnek dosyalara/testlere kopyalanmamalı. Gerçek run verileri `.ragnoz/` altında ve git dışı olmalı.
  - Rapor maskelemesi `--redact`; varsayılan olarak network credentials, belge metni ve private içerik rapora sızmamalı.
  - Python 3.11+, macOS/Windows/Linux ve UTF-8; GPU opsiyonel, CPU varsayılan; soru başı hata `SYS_ERROR` olmalı.
  - Önbellekli diagnose 100 soruda ≤10 sn; JSONL 1.000 iz eval ≤30 sn; yeni aşama adaptörü için ≤50 satır örnek; çekirdek test kapsamı ≥%85 hedefleri korunmalı.
  - README’de kurulum, iki dakikalık ağsız demo ve üç entegrasyon yolu açıklanmalı.
