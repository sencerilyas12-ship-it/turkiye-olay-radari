
import json
from pathlib import Path

DOSYA = Path("kaynaklar.json")

ILLER = [
    "Adana",
    "Adıyaman",
    "Afyonkarahisar",
    "Ağrı",
    "Amasya",
    "Ankara",
    "Antalya",
    "Artvin",
    "Aydın",
    "Balıkesir",
    "Bilecik",
    "Bingöl",
    "Bitlis",
    "Bolu",
    "Burdur",
    "Bursa",
    "Çanakkale",
    "Çankırı",
    "Çorum",
    "Denizli",
    "Diyarbakır",
    "Edirne",
    "Elazığ",
    "Erzincan",
    "Erzurum",
    "Eskişehir",
    "Gaziantep",
    "Giresun",
    "Gümüşhane",
    "Hakkari",
    "Hatay",
    "Isparta",
    "Mersin",
    "İstanbul",
    "İzmir",
    "Kars",
    "Kastamonu",
    "Kayseri",
    "Kırklareli",
    "Kırşehir",
    "Kocaeli",
    "Konya",
    "Kütahya",
    "Malatya",
    "Manisa",
    "Kahramanmaraş",
    "Mardin",
    "Muğla",
    "Muş",
    "Nevşehir",
    "Niğde",
    "Ordu",
    "Rize",
    "Sakarya",
    "Samsun",
    "Siirt",
    "Sinop",
    "Sivas",
    "Tekirdağ",
    "Tokat",
    "Trabzon",
    "Tunceli",
    "Şanlıurfa",
    "Uşak",
    "Van",
    "Yozgat",
    "Zonguldak",
    "Aksaray",
    "Bayburt",
    "Karaman",
    "Kırıkkale",
    "Batman",
    "Şırnak",
    "Bartın",
    "Ardahan",
    "Iğdır",
    "Yalova",
    "Karabük",
    "Kilis",
    "Osmaniye",
    "Düzce"
]


def kaynaklari_yukle():
    if not DOSYA.exists():
        return {"iller": [], "kaynaklar": []}

    with DOSYA.open("r", encoding="utf-8") as dosya:
        veri = json.load(dosya)

    if not isinstance(veri, dict):
        raise ValueError("kaynaklar.json dosyasının yapısı hatalı.")

    veri.setdefault("kaynaklar", [])

    if not isinstance(veri["kaynaklar"], list):
        raise ValueError("Kaynak listesi geçerli değil.")

    return veri


def kaynaklari_kaydet(veri):
    with DOSYA.open("w", encoding="utf-8") as dosya:
        json.dump(
            veri,
            dosya,
            ensure_ascii=False,
            indent=2
        )


def ana():
    veri = kaynaklari_yukle()
    veri["iller"] = ILLER

    kaynaklari_kaydet(veri)

    print("TÜRKİYE OLAY RADARI")
    print("İl sayısı:", len(ILLER))
    print("Kayıtlı kaynak:", len(veri["kaynaklar"]))
    print("Kontrol başarıyla tamamlandı.")


if __name__ == "__main__":
    ana()
