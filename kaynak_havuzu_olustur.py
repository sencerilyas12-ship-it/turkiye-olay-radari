
# ============================================================
# MİHVER - KAYNAK HAVUZU OLUŞTURUCU
# Sürüm: 1.0
#
# Amaç:
# 1. Basın İlan Kurumu süreli yayınlar listesini almak
# 2. Gazete ve internet haber sitelerini ayırmak
# 3. İl / ilçe / yayın türü bilgilerini çıkarmak
# 4. Mevcut kaynaklar.json dosyasını koruyarak birleştirmek
# 5. Kaynakları doğrulanma durumlarına göre sınıflandırmak
#
# Yalnızca Python standart kütüphanesi kullanılır.
# ============================================================

import json
import re
import time
import hashlib
import urllib.request
import urllib.error

from pathlib import Path
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin


# ------------------------------------------------------------
# DOSYA VE SİSTEM AYARLARI
# ------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

KAYNAK_DOSYASI = BASE_DIR / "kaynaklar.json"
YEDEK_DOSYASI = BASE_DIR / "kaynaklar_yedek.json"
ISTATISTIK_DOSYASI = BASE_DIR / "kaynak_havuzu_istatistikleri.json"

BIK_ADRESLERI = [
    "https://ilanbis.bik.gov.tr/uygulamalar/aylikliste",
    "https://gazete.bik.gov.tr/Uygulamalar/AylikListe"
]

USER_AGENT = (
    "Mozilla/5.0 (compatible; MIHVER-KaynakHavuzu/1.0; "
    "+https://mihver.pages.dev)"
)

ZAMAN_ASIMI = 30

# Aynı çalışmada gereksiz istek yapılmasını engeller.
ISTEK_BEKLEME = 1.0

# ------------------------------------------------------------
# 81 İL
# ------------------------------------------------------------

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

IL_NORMAL = {
    re.sub(r"[^a-zçğıöşü]", "", il.lower()): il
    for il in ILLER
}


# ------------------------------------------------------------
# KAYNAK TİPLERİ
# ------------------------------------------------------------

KAYNAK_TIPLERI = {
    "bik_resmi_ilan_gazetesi": "BİK resmî ilan ve reklam alan gazete",
    "bik_bekleme_gazetesi": "BİK bekleme süresindeki gazete",
    "bik_resmi_ilan_internet": "BİK resmî ilan ve reklam alan internet haber sitesi",
    "bik_bekleme_internet": "BİK bekleme süresindeki internet haber sitesi",
    "bik_reklam_internet": "BİK yalnızca reklam alan internet haber sitesi",
    "bik_reklam_basili": "BİK reklam alan basılı yayın",
    "bik_diger": "BİK diğer süreli yayın"
}


# ------------------------------------------------------------
# GENEL YARDIMCILAR
# ------------------------------------------------------------

def simdi():
    return datetime.now(timezone.utc).isoformat()


def temizle(metin):
    metin = metin or ""
    metin = re.sub(r"<[^>]+>", " ", metin)
    metin = re.sub(r"\s+", " ", metin)
    return metin.strip()


def kimlik_uret(deger):
    return hashlib.sha256(
        deger.lower().strip().encode("utf-8")
    ).hexdigest()[:24]


def il_normalize(metin):
    metin = (metin or "").strip().lower()
    metin = re.sub(r"[^a-zçğıöşü]", "", metin)
    return IL_NORMAL.get(metin)


def alan_adi(url):
    try:
        alan = urlparse(url).netloc.lower()
        alan = alan.split("@")[-1].split(":")[0]

        if alan.startswith("www."):
            alan = alan[4:]

        return alan
    except Exception:
        return ""


def guvenli_json_oku(dosya, varsayilan):
    if not dosya.exists():
        return varsayilan

    try:
        with dosya.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as hata:
        raise RuntimeError(
            f"{dosya.name} okunamadı. "
            f"Dosya korunuyor. Hata: {hata}"
        )


def guvenli_json_yaz(dosya, veri):
    gecici = dosya.with_name(dosya.name + ".tmp")

    with gecici.open("w", encoding="utf-8") as f:
        json.dump(
            veri,
            f,
            ensure_ascii=False,
            indent=2
        )

    gecici.replace(dosya)


def yedek_al():
    if KAYNAK_DOSYASI.exists():
        if not YEDEK_DOSYASI.exists():
            with KAYNAK_DOSYASI.open(
                "rb"
            ) as kaynak:
                icerik = kaynak.read()

            with YEDEK_DOSYASI.open(
                "wb"
            ) as hedef:
                hedef.write(icerik)


# ------------------------------------------------------------
# HTML TABLO OKUYUCU
# ------------------------------------------------------------

class TabloOkuyucu(HTMLParser):

    def __init__(self):
        super().__init__()

        self.tablo_satirlari = []
        self.satir = None
        self.hucre = None
        self.linkler = []
        self.basliklar = []
        self.aktif_link = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "tr":
            self.satir = []

        elif tag in ("td", "th") and self.satir is not None:
            self.hucre = {
                "metin": "",
                "linkler": []
            }

        elif tag == "a":
            href = attrs.get("href", "")

            if href:
                self.aktif_link = {
                    "href": href,
                    "metin": ""
                }

    def handle_data(self, data):
        if self.hucre is not None:
            self.hucre["metin"] += data

        if self.aktif_link is not None:
            self.aktif_link["metin"] += data

    def handle_endtag(self, tag):

        if tag == "a" and self.aktif_link is not None:
            if self.hucre is not None:
                self.hucre["linkler"].append(
                    self.aktif_link
                )

            self.aktif_link = None

        elif tag in ("td", "th") and self.hucre is not None:
            self.hucre["metin"] = temizle(
                self.hucre["metin"]
            )

            self.satir.append(self.hucre)
            self.hucre = None

        elif tag == "tr" and self.satir is not None:
            if self.satir:
                self.tablo_satirlari.append(self.satir)

            self.satir = None


# ------------------------------------------------------------
# WEB SAYFASI İNDİRME
# ------------------------------------------------------------

def web_sayfasi_indir(url):

    istek = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml"
        }
    )

    try:
        with urllib.request.urlopen(
            istek,
            timeout=ZAMAN_ASIMI
        ) as cevap:

            icerik = cevap.read()

            kodlama = cevap.headers.get_content_charset()

            if not kodlama:
                kodlama = "utf-8"

            return icerik.decode(
                kodlama,
                errors="replace"
            )

    except (
        urllib.error.URLError,
        TimeoutError,
        OSError
    ) as hata:

        print("Sayfa indirilemedi:", url)
        print("Hata:", str(hata)[:200])

        return None


# ------------------------------------------------------------
# BİK SAYFA BAŞLIKLARINDAN BİLGİ ÇIKARMA
# ------------------------------------------------------------

def basliktan_bilgi(metin):

    metin = temizle(metin)
    buyuk = metin.upper()

    il = None

    for aday in sorted(ILLER, key=len, reverse=True):
        if re.search(
            r"\b" + re.escape(aday.upper()) + r"\b",
            buyuk
        ):
            il = aday
            break

    ilce = None

    # Örnek:
    # İSTANBUL Silivri
    # ANKARA Haymana
    if il:
        eslesme = re.search(
            re.escape(il.upper()) + r"\s+(.+)$",
            buyuk
        )

        if eslesme:
            olasi = eslesme.group(1).strip()

            if olasi and len(olasi) < 60:
                ilce = olasi.title()

    return il, ilce


def bik_turunu_bul(baslik):

    b = (baslik or "").lower()

    if "bekleme süresi" in b and "internet" in b:
        return "bik_bekleme_internet"

    if "bekleme süresi" in b and "gazete" in b:
        return "bik_bekleme_gazetesi"

    if "reklam alan internet" in b:
        return "bik_reklam_internet"

    if "reklam alan basılı" in b:
        return "bik_reklam_basili"

    if "resmî ilan" in b and "internet" in b:
        return "bik_resmi_ilan_internet"

    if "resmî ilan" in b and "gazete" in b:
        return "bik_resmi_ilan_gazetesi"

    return "bik_diger"


# ------------------------------------------------------------
# BİK TABLOLARINI AYRIŞTIRMA
# ------------------------------------------------------------

def bik_sayfasini_ayristir(html, sayfa_url):

    parser = TabloOkuyucu()
    parser.feed(html)

    kayitlar = []

    aktif_baslik = ""
    aktif_il = None
    aktif_ilce = None

    for satir in parser.tablo_satirlari:

        hucreler = [
            hucre.get("metin", "")
            for hucre in satir
        ]

        satir_metin = " ".join(hucreler).strip()

        if not satir_metin:
            continue

        # Başlık satırlarını yakala.
        if (
            "GAZETELERİ" in satir_metin.upper()
            or "İNTERNET HABER SİTELERİ" in satir_metin.upper()
            or "BEKLEME SÜRESİ" in satir_metin.upper()
            or "REKLAM ALAN" in satir_metin.upper()
        ):

            aktif_baslik = satir_metin
            bulunan_il, bulunan_ilce = basliktan_bilgi(
                satir_metin
            )

            if bulunan_il:
                aktif_il = bulunan_il

            if bulunan_ilce:
                aktif_ilce = bulunan_ilce

            continue

        # Sayfa içindeki il başlıkları bazen tek hücreli olur.
        if len(hucreler) == 1:
            bulunan_il, bulunan_ilce = basliktan_bilgi(
                satir_metin
            )

            if bulunan_il:
                aktif_il = bulunan_il

            if bulunan_ilce:
                aktif_ilce = bulunan_ilce

            continue

        tur = bik_turunu_bul(aktif_baslik)

        ad = ""
        url = ""

        # BİK internet listelerinde alan adı çoğunlukla
        # ilk hücrede yazılıdır.
        for hucre in hucreler:
            if re.match(
                r"^(https?://)?(www\.)?[\w.-]+\.[a-z]{2,}",
                hucre.lower()
            ):
                aday = hucre.strip()

                if not aday.startswith("http"):
                    aday = "https://" + aday

                url = aday
                ad = alan_adi(url)
                break

        # Basılı gazete listelerinde ilk hücre gazete adıdır.
        if not url:
            ad = hucreler[0].strip()

        # Sıra numarası gibi kayıtları atla.
        if not ad:
            continue

        if ad.lower() in (
            "sıra",
            "gazete adı",
            "süreli yayın adı",
            "yayın yeri"
        ):
            continue

        kayitlar.append({
            "ad": ad,
            "url": url,
            "il": aktif_il,
            "ilce": aktif_ilce,
            "kaynak_tipi": tur,
            "kaynak_referansi": sayfa_url,
            "yayinci_turu": (
                "internet_haber_sitesi"
                if url
                else "basili_yayin"
            )
        })

    return kayitlar


# ------------------------------------------------------------
# BİK KAYNAK HAVUZU
# ------------------------------------------------------------

def bik_kaynaklarini_getir():

    bulunanlar = []
    basarili = False

    for adres in BIK_ADRESLERI:

        print("\nBİK listesi kontrol ediliyor:")
        print(adres)

        html = web_sayfasi_indir(adres)

        if not html:
            continue

        kayitlar = bik_sayfasini_ayristir(
            html,
            adres
        )

        if kayitlar:
            bulunanlar.extend(kayitlar)
            basarili = True

            print(
                "Bu sayfadan bulunan kayıt:",
                len(kayitlar)
            )

        time.sleep(ISTEK_BEKLEME)

    if not basarili:
        print(
            "UYARI: BİK sayfalarından kayıt "
            "ayrıştırılamadı."
        )

    return bulunanlar


# ------------------------------------------------------------
# KAYNAK KAYDI OLUŞTURMA
# ------------------------------------------------------------

def kaynak_kaydi_olustur(bilgi):

    ad = temizle(bilgi.get("ad"))
    url = temizle(bilgi.get("url"))

    alan = alan_adi(url) if url else ""

    il = bilgi.get("il")
    ilce = bilgi.get("ilce")

    tur = bilgi.get("kaynak_tipi", "bik_diger")

    if not ad:
        return None

    kimlik = kimlik_uret(
        alan if alan else ad + "|" + str(il) + "|" + str(ilce)
    )

    return {
        "kimlik": kimlik,
        "il": il,
        "ilce": ilce,
        "il_baglantilari": [il] if il else [],
        "ad": ad,
        "url": url,
        "alan": alan,
        "tur": tur,
        "kaynak_tipi": tur,
        "kaynak_tipi_aciklama": KAYNAK_TIPLERI.get(
            tur,
            "Diğer kaynak"
        ),
        "durum": "aday",
        "kaynak_referansi": bilgi.get(
            "kaynak_referansi",
            ""
        ),
        "kesif_tarihi": simdi(),
        "son_kontrol": None,
        "dogrulama": {
            "adres": "kontrol_edilmedi",
            "il": (
                "bik_listesinde_bulundu"
                if il
                else "belirsiz"
            ),
            "ilce": (
                "bik_listesinde_bulundu"
                if ilce
                else "belirsiz"
            ),
            "yayinci": "bik_listesinde_bulundu",
            "rss": "kontrol_edilmedi"
        }
    }


# ------------------------------------------------------------
# TEKİL KAYNAK ANAHTARI
# ------------------------------------------------------------

def kaynak_anahtari(kaynak):

    alan = (kaynak.get("alan") or "").lower().strip()

    if alan:
        return "alan:" + alan

    kimlik = kaynak.get("kimlik")

    if kimlik:
        return "kimlik:" + kimlik

    return "ad:" + (
        kaynak.get("ad", "").lower().strip()
    )


# ------------------------------------------------------------
# MEVCUT KAYNAKLARLA BİRLEŞTİRME
# ------------------------------------------------------------

def kaynaklari_birlestir(mevcut, yeni):

    indeks = {}

    for kayit in mevcut:

        if not isinstance(kayit, dict):
            continue

        anahtar = kaynak_anahtari(kayit)
        indeks[anahtar] = kayit

    eklenen = 0
    guncellenen = 0

    for yeni_kayit in yeni:

        kayit = kaynak_kaydi_olustur(yeni_kayit)

        if kayit is None:
            continue

        anahtar = kaynak_anahtari(kayit)

        if anahtar not in indeks:

            mevcut.append(kayit)
            indeks[anahtar] = kayit
            eklenen += 1

        else:

            eski = indeks[anahtar]

            # Eski kaydın doğrulama ve kullanıcı
            # tarafından girilmiş bilgilerini ezme.
            if not eski.get("url") and kayit.get("url"):
                eski["url"] = kayit["url"]

            if not eski.get("il") and kayit.get("il"):
                eski["il"] = kayit["il"]

            if not eski.get("ilce") and kayit.get("ilce"):
                eski["ilce"] = kayit["ilce"]

            eski.setdefault("il_baglantilari", [])

            il = kayit.get("il")

            if il and il not in eski["il_baglantilari"]:
                eski["il_baglantilari"].append(il)

            eski.setdefault("kesif_referanslari", [])

            referans = kayit.get("kaynak_referansi")

            if (
                referans
                and referans not in eski["kesif_referanslari"]
            ):
                eski["kesif_referanslari"].append(referans)

            guncellenen += 1

    return eklenen, guncellenen


# ------------------------------------------------------------
# ANA PROGRAM
# ------------------------------------------------------------

def ana():

    print("=" * 60)
    print("MİHVER KAYNAK HAVUZU OLUŞTURUCU")
    print("=" * 60)

    # Mevcut dosya okunamıyorsa işlem durur.
    # Böylece bozuk dosyanın üzerine yazılmaz.
    veri = guvenli_json_oku(
        KAYNAK_DOSYASI,
        {
            "iller": ILLER,
            "kaynaklar": []
        }
    )

    if not isinstance(veri, dict):
        raise RuntimeError(
            "kaynaklar.json bir JSON nesnesi olmalıdır."
        )

    if not isinstance(veri.get("kaynaklar"), list):
        raise RuntimeError(
            "kaynaklar.json içindeki kaynaklar alanı liste değil."
        )

    # İşlem öncesi yedek.
    yedek_al()

    # Eksik illeri ekle, mevcut illeri silme.
    veri.setdefault("iller", [])

    for il in ILLER:
        if il not in veri["iller"]:
            veri["iller"].append(il)

    print("Mevcut kaynak sayısı:", len(veri["kaynaklar"]))

    # BİK listesini indir ve ayrıştır.
    bik_kayitlari = bik_kaynaklarini_getir()

    print(
        "\nBİK üzerinden ayrıştırılan toplam kayıt:",
        len(bik_kayitlari)
    )

    # Kaynakları mevcut havuzla birleştir.
    eklenen, guncellenen = kaynaklari_birlestir(
        veri["kaynaklar"],
        bik_kayitlari
    )

    veri["son_havuz_guncellemesi"] = simdi()

    veri.setdefault("envanter_bilgisi", {})

    veri["envanter_bilgisi"].update({
        "il_sayisi": 81,
        "bik_kayit_sayisi": len(bik_kayitlari),
        "bu_calismada_eklenen": eklenen,
        "bu_calismada_eslesen": guncellenen,
        "son_guncelleme": simdi(),
        "aciklama": (
            "BİK kayıtları aday kaynak havuzuna eklenmiştir. "
            "İnternet adresi, RSS, yayıncılık faaliyeti ve "
            "yerel kapsam ayrıca doğrulanmalıdır."
        )
    })

    # Dosyayı güvenli şekilde kaydet.
    guvenli_json_yaz(
        KAYNAK_DOSYASI,
        veri
    )

    # İstatistikleri ayrı dosyaya yaz.
    istatistik = {
        "calisma_tarihi": simdi(),
        "bik_sayfa_adet": len(BIK_ADRESLERI),
        "bik_ayristirilan_kayit": len(bik_kayitlari),
        "yeni_eklenen": eklenen,
        "mevcut_kayitla_eslesen": guncellenen,
        "toplam_kaynak": len(veri["kaynaklar"]),
        "yedek_dosyasi": YEDEK_DOSYASI.name
    }

    guvenli_json_yaz(
        ISTATISTIK_DOSYASI,
        istatistik
    )

    print("\n" + "=" * 60)
    print("KAYNAK HAVUZU İŞLEMİ TAMAMLANDI")
    print("=" * 60)

    print("BİK kayıtları:", len(bik_kayitlari))
    print("Yeni eklenen:", eklenen)
    print("Mevcut kayıtlarla eşleşen:", guncellenen)
    print("Toplam kaynak:", len(veri["kaynaklar"]))

    print("\nDosyalar:")
    print("-", KAYNAK_DOSYASI.name)
    print("-", YEDEK_DOSYASI.name)
    print("-", ISTATISTIK_DOSYASI.name)

    print("\nNot: Aday kaynaklar henüz doğrulanmış kaynak değildir.")


if __name__ == "__main__":
    ana()
