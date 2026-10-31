# Changelog

Bu proje [Semantic Versioning](https://semver.org/) kullanır. Etiketler kullanıcı tarafından atılır; bu dosya yalnız içerik hazırlığıdır.

## [0.2.0] — hazırlanıyor

### Eklenenler

- **Kural motoru YAML'a taşındı.** 11 çekirdek anti-pattern kuralı artık kod içine gömülü sabitler değil, `src/ragnoz/data/rules/*.yaml` kataloğunda versiyonlu kayıtlar. `rules_by_symptom()` ters indeksi `triage`'ın temelini oluşturur.
- **`ragnoz golden quickstart`**: gevşek CSV/JSONL/markdown soru-cevap listesini şemalı `golden.jsonl`'a çevirir, otomatik `golden validate` çalıştırır, satır numaralı hata raporu verir. 5'ten az kayıtta düşük-güven uyarısı basar.
- **`ragnoz triage "şikayet"`**: doğal dil şikayetini semptomlarla eşleştirir. Golden+traces yoksa yalnız yönlendirme (`Guidance` tipi; düzeltme önerisi taşıyamaz, bu tip seviyesinde zorlanır), varsa gerçek `diagnose` çıktısını filtreler.
- **`ragnoz inspect` + `ragnoz architecture approve`**: adapter kaynağını statik AST taramasıyla dosya+satır kanıtlı bir TASLAK (`architecture.draft.yaml`) üretir. `diagnose`/`triage`/`report` onaysız taslağı ölçülmüş girdi saymaz ve yapısal olarak reddeder.
- GitHub Actions CI (`.github/workflows/ci.yml`): her push/PR'da Python 3.11 ve 3.12'de ruff + mypy + pytest (`--cov-fail-under=85`).
- `CHANGELOG.md` eklendi (bu dosya).

### Değişenler

- **CLI modüllere bölündü.** Tek parça `cli.py` (575 satır), davranış değişmeden, stage bazlı alt modüllere bölündü: `src/ragnoz/cli/{demo,golden,pipeline,diagnosis,experiment,architecture}.py`. Giriş noktası (`ragnoz.cli:app`) aynı kaldı.
- **Demo verisi tekilleştirildi.** `examples/demo/` kaldırıldı; `src/ragnoz/data/demo/` (pakete ve wheel'e dahil) artık tek kaynak. README ve iç dokümantasyon buna göre güncellendi.
- Coverage ölçümü gerçek kodu gösterecek şekilde düzeltildi: `data/demo/adapter.py` ve `data/demo/__init__.py` (son kullanıcıya yönelik örnek kod, kendi test paketimizce hiç çalıştırılmaz) `[tool.coverage.run]` altında `omit` edildi; `[tool.coverage.report] fail_under = 85` eklendi.
- `tool_version` artık manifest dosyalarında (`run`/`eval` çıktısı) sabit metin değil, `ragnoz.__version__`'den okunuyor.

### Test ve kapsam

- 29 → **158 pytest testi**; satır kapsamı %87.48 → **%95.38** (omit sonrası).
- Eşik altındaki üç modül %100'e çıkarıldı: `statistics.py` (%83), `importers.py` (%74), `runner.py` (%84) — Wilson/McNemar için literatürdeki/elle hesaplanmış bilinen değerlerle doğrulanan testler dahil.
- `golden quickstart`/`triage`/`inspect` için hata yolu testleri eklendi (bozuk CSV, eksik alan, eşleşmeyen şikayet, boş golden set).

## [0.1.0]

- İlk MVP: Python 3.11+ Typer CLI, Pydantic şemalar, altı aşamalı önbellekli yürütücü, 11 çekirdek anti-pattern teşhisi, Wikipedia mini-demo, tek dosya HTML rapor.
