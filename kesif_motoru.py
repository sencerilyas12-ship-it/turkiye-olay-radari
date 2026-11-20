import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

DOSYA = "kaynaklar.json"

ARAMA_KELIMELERI = [
    "yerel haber",
    "ilçe haberleri",
    "belediye haberleri",
    "adliye haberleri",
    "son dakika"
]

ILLER = [
    "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Amasya",
    "Ankara", "Antalya", "Artvin", "Aydın", "Balıkesir",
    "Bilecik", "Bingöl", "Bitlis", "Bolu", "Burdur",
    "Bursa", "Çanakkale", "Çankırı", "Çorum", "Denizli",
    "Diyarbakır", "Edirne", "Elazığ", "Erzincan", "Erzurum",
    "Eskişehir", "Gaziantep", "Giresun", "Gümüşhane", "Hakkari",
    "Hatay", "Isparta", "Mersin", "İstanbul", "İzmir",
    "Kars", "Kastamonu", "Kayseri", "Kırklareli", "Kırşehir",
    "Kocaeli", "Konya", "Kütahya", "Malatya", "Manisa",
    "Kahramanmaraş", "Mardin", "Muğla", "Muş", "Nevşehir",
    "Niğde", "Ordu", "Rize", "Sakarya", "Samsun",
    "Siirt", "Sinop", "Sivas", "Tekirdağ", "Tokat",
    "Trabzon", "Tunceli", "Şanlıurfa", "Uşak", "Van",
    "Yozgat", "Zonguldak", "Aksaray", "Bayburt", "Karaman",
    "Kırıkkale", "Batman", "Şırnak", "Bartın", "Ardahan",
    "Iğdır", "Yalova", "Karabük", "Kilis", "Osmaniye",
    "Düzce"
]

def kaynaklari_yukle():
    try:
        with open(DOSYA, "r", encoding="utf-8") as dosya:
            return json.load(dosya)
    except FileNotFoundError:
        return {"iller": ILLER, "kaynaklar": []}

def kaynaklari_kaydet(veri):
    with open(DOSYA, "w", encoding="utf-8") as dosya:
        json.dump(veri, dosya, ensure_ascii=False, indent=2)

def site_kontrol(url):
    try:
        cevap = requests.get(
            url,
            timeout=10,
            headers={"User-Agent": "TurkiyeOlayRadari/1.0"}
        )
        return cevap.status_code == 200
    except requests.RequestException:
        return False

def kaynak_ekle(veri, il, ad, url, tur):
    alan = urlparse(url).netloc.lower()

    for kaynak in veri["kaynaklar"]:
        if kaynak["alan"] == alan:
            return False

    if not site_kontrol(url):
        return False

    veri["kaynaklar"].append({
        "il": il,
        "ad": ad,
        "url": url,
        "alan": alan,
        "tur": tur,
        "durum": "aktif"
    })

    return True

def rapor_goster(veri):
    print("TÜRKİYE OLAY RADARI")
    print("İl sayısı:", len(ILLER))
    print("Kayıtlı kaynak:", len(veri["kaynaklar"]))

if __name__ == "__main__":
    veriler = kaynaklari_yukle()
    veriler["iller"] = ILLER
    kaynaklari_kaydet(veriler)
    rapor_goster(veriler)
