# Wikipedia wiki-mini demo

- `golden.jsonl`: 40 soru; 8 cevapsız, sayısal/olgusal, TR↔EN, çok adımlı ve exact-ID örnekler. `golden validate` ile şema ve alıntılar denetlenebilir.
- `wiki-mini.revisions.json`: 20 sabit article revision/page ID.
- `SOURCES.md`: revision URL ve CC BY-SA 4.0 atıfları.
- `pipelines/`: naive, advanced ve kasıtlı bozuk mimari profilleri.
- `EXPECTED_DIAGNOSIS.yaml`: demo kurallarının beklenen sınırlı bulguları.
- `adapter.py`: yalnızca `demo init` ile yerel korpus oluşturulduğunda kullanılabilen basit kelime-örtüşmesi/extractive örnek adapter.

`ragnoz demo run` önceden hazırlanmış deterministik sentetik izleri çalıştırır; bunlar gerçek retrieval motorlarının benchmark sonucu değildir. `ragnoz demo init` sabit Wikipedia revision metnini yalnız `.ragnoz/demo-corpus/` altına indirir, tam metin depoya eklenmez. Atıf/lisans ayrıntısı `SOURCES.md` içindedir.
