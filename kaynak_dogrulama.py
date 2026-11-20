
# ============================================================
# MİHVER - KAYNAK DOĞRULAMA MOTORU
# Sürüm: 1.0
#
# Görevleri:
# 1. Kaynak internet sitelerinin erişilebilirliğini kontrol eder.
# 2. HTTP yönlendirmelerini takip eder.
# 3. RSS ve Atom adreslerini keşfeder.
# 4. Bulunan RSS adreslerini test eder.
# 5. Alan adı ve yönlendirme bilgilerini kaydeder.
# 6. İl / ilçe bilgilerini otomatik olarak kesinleştirmez.
# 7. Kaynakları otomatik olarak aktif hale getirmez.
# 8. Her çalışmada sınırlı sayıda kaynak kontrol eder.
# 9. Kaldığı sıradan devam eder.
# 10. Mevcut haber ve kaynak kayıtlarını silmez.
#
# Yalnızca Python standart kütüphanesi kullanılır.
# ============================================================

import json
import re
import time
import hashlib
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET

from pathlib import Path
from datetime import datetime, timezone
from html.parser import HTMLParser


# ------------------------------------------------------------
# DOSYA AYARLARI
# ------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

KAYNAK_DOSYASI = BASE_DIR / "kaynaklar.json"
DURUM_DOSYASI = BASE_DIR / "dogrulama_durumu.json"
RAPOR_DOSYASI = BASE_DIR / "kaynak_dogrulama_raporu.json"

USER_AGENT = (
    "Mozilla/5.0 (compatible; MIHVER-Validator/1.0; "
    "+https://mihver.pages.dev)"
)

TIMEOUT = 15

# Her çalışmada kontrol edilecek kaynak sayısı.
KONTROL_LIMITI = 40

# İstekler arasındaki bekleme süresi.
BEKLEME = 1.0

# Ana sayfadan alınabilecek azami veri.
MAKSIMUM_HTML = 1_000_000

# RSS kontrolünde alınabilecek azami veri.
MAKSIMUM_XML = 500_000


# ------------------------------------------------------------
# GENEL YARDIMCILAR
# ------------------------------------------------------------

def simdi():
    return datetime.now(timezone.utc).isoformat()


def json_oku(dosya, varsayilan):
    if not dosya.exists():
        return varsayilan

    with dosya.open("r", encoding="utf-8") as f:
        return json.load(f)


def json_yaz(dosya, veri):
    gecici = dosya.with_name(dosya.name + ".tmp")

    with gecici.open("w", encoding="utf-8") as f:
        json.dump(
            veri,
            f,
            ensure_ascii=False,
            indent=2
        )

    gecici.replace(dosya)


def metin_temizle(deger):
    return re.sub(r"\s+", " ", str(deger or "")).strip()


def alan_adi(url):
    try:
        alan = urllib.parse.urlparse(url).hostname or ""
        alan = alan.lower().strip()

        if alan.startswith("www."):
            alan = alan[4:]

        return alan
    except Exception:
        return ""


def guvenli_url(url):
    if not isinstance(url, str):
        return ""

    url = url.strip()

    if not url:
        return ""

    if url.startswith("//"):
        url = "https:" + url

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urllib.parse.urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return ""

        if not parsed.hostname:
            return ""

        return url

    except Exception:
        return ""


def kimlik_uret(metin):
    return hashlib.sha256(
        metin.encode("utf-8")
    ).hexdigest()[:20]


# ------------------------------------------------------------
# HTTP İSTEKLERİ
# ------------------------------------------------------------

def http_istek(url, limit=MAKSIMUM_HTML):

    istek = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml,application/rss+xml,"
                "application/atom+xml,*/*"
            )
        }
    )

    try:
        with urllib.request.urlopen(
            istek,
            timeout=TIMEOUT
        ) as cevap:

            veri = cevap.read(limit + 1)

            if len(veri) > limit:
                veri = veri[:limit]

            return {
                "basarili": True,
                "durum_kodu": getattr(
                    cevap,
                    "status",
                    200
                ),
                "son_url": cevap.geturl(),
                "icerik_tipi": cevap.headers.get(
                    "Content-Type",
                    ""
                ),
                "veri": veri,
                "hata": None
            }

    except urllib.error.HTTPError as hata:

        return {
            "basarili": False,
            "durum_kodu": hata.code,
            "son_url": hata.geturl(),
            "icerik_tipi": "",
            "veri": b"",
            "hata": "HTTP " + str(hata.code)
        }

    except Exception as hata:

        return {
            "basarili": False,
            "durum_kodu": None,
            "son_url": url,
            "icerik_tipi": "",
            "veri": b"",
            "hata": str(hata)[:250]
        }


# ------------------------------------------------------------
# HTML İÇİNDEN RSS / ATOM ADRESLERİNİ BULMA
# ------------------------------------------------------------

class BeslemeBulucu(HTMLParser):

    def __init__(self):
        super().__init__()
        self.beslemeler = []

    def handle_starttag(self, tag, attrs):

        if tag.lower() != "link":
            return

        attrs = dict(attrs)

        rel = attrs.get("rel", "").lower()
        tip = attrs.get("type", "").lower()
        href = attrs.get("href", "")

        if not href:
            return

        if "alternate" not in rel:
            return

        if (
            "rss" in tip
            or "atom" in tip
            or "xml" in tip
        ):
            self.beslemeler.append({
                "href": href,
                "type": tip
            })


def html_beslemelerini_bul(html, ana_url):

    bulunan = []

    parser = BeslemeBulucu()

    try:
        parser.feed(html)
    except Exception:
        return bulunan

    for kayit in parser.beslemeler:

        adres = urllib.parse.urljoin(
            ana_url,
            kayit["href"]
        )

        adres = guvenli_url(adres)

        if adres and adres not in bulunan:
            bulunan.append(adres)

    return bulunan


# ------------------------------------------------------------
# YAYGIN RSS / ATOM ADRESLERİ
# ------------------------------------------------------------

def olasi_besleme_adresleri(ana_url):

    yollar = [
        "/feed",
        "/feed/",
        "/rss",
        "/rss/",
        "/rss.xml",
        "/feed.xml",
        "/atom.xml",
        "/feeds/posts/default",
        "/?feed=rss2",
        "/wp-json/wp/v2/posts"
    ]

    bulunan = []

    for yol in yollar:

        adres = urllib.parse.urljoin(
            ana_url.rstrip("/") + "/",
            yol.lstrip("/")
        )

        if adres not in bulunan:
            bulunan.append(adres)

    return bulunan


# ------------------------------------------------------------
# RSS / ATOM XML KONTROLÜ
# ------------------------------------------------------------

def xml_besleme_gecerli(xml_verisi):

    if not xml_verisi:
        return False

    try:
        kok = ET.fromstring(xml_verisi)

        etiket = kok.tag.lower()

        # RSS
        if etiket.endswith("rss"):
            return True

        # Atom
        if etiket.endswith("feed"):
            return True

        # RDF tabanlı RSS
        if etiket.endswith("rdf"):
            return True

        return False

    except ET.ParseError:
        return False


def besleme_kontrol(adres):

    sonuc = http_istek(
        adres,
        limit=MAKSIMUM_XML
    )

    if not sonuc["basarili"]:
        return {
            "adres": adres,
            "durum": "erisilemedi",
            "http_kodu": sonuc["durum_kodu"]
        }

    gecerli = xml_besleme_gecerli(
        sonuc["veri"]
    )

    if gecerli:
        durum = "rss_atom_gecerli"
    else:
        durum = "xml_besleme_degil"

    return {
        "adres": adres,
        "durum": durum,
        "http_kodu": sonuc["durum_kodu"],
        "son_url": sonuc["son_url"]
    }


# ------------------------------------------------------------
# ROBOTS.TXT KONTROLÜ
# ------------------------------------------------------------

def robots_kontrol(ana_url):

    parsed = urllib.parse.urlparse(ana_url)

    robots_url = (
        parsed.scheme
        + "://"
        + parsed.netloc
        + "/robots.txt"
    )

    sonuc = http_istek(
        robots_url,
        limit=100_000
    )

    if not sonuc["basarili"]:

        if sonuc["durum_kodu"] == 404:
            durum = "robots_dosyasi_yok"
        else:
            durum = "kontrol_edilemedi"

        return {
            "adres": robots_url,
            "durum": durum
        }

    metin = sonuc["veri"].decode(
        "utf-8",
        errors="replace"
    )

    return {
        "adres": robots_url,
        "durum": "robots_dosyasi_bulundu",
        "icerik": metin[:20000]
    }


# ------------------------------------------------------------
# BİR KAYNAĞIN TAM KONTROLÜ
# ------------------------------------------------------------

def kaynak_kontrol(kaynak):

    url = guvenli_url(
        kaynak.get("url", "")
    )

    eski_alan = (
        kaynak.get("alan")
        or alan_adi(url)
    )

    rapor = {
        "kontrol_tarihi": simdi(),
        "url": url,
        "eski_alan": eski_alan,
        "erisim": "kontrol_edilmedi",
        "yonlendirme": None,
        "yeni_alan": None,
        "http_kodu": None,
        "rss_adresleri": [],
        "rss_durumu": "bulunamadi",
        "robots": None,
        "hata": None
    }

    if not url:

        rapor["erisim"] = "gecersiz_adres"
        rapor["hata"] = "Kaynak URL alanı boş veya geçersiz."
        return rapor

    sonuc = http_istek(url)

    rapor["http_kodu"] = sonuc["durum_kodu"]

    if not sonuc["basarili"]:

        rapor["erisim"] = "erisilemedi"
        rapor["hata"] = sonuc["hata"]

        return rapor

    son_url = sonuc["son_url"]

    yeni_alan = alan_adi(son_url)

    rapor["erisim"] = "erisilebilir"
    rapor["son_url"] = son_url
    rapor["yeni_alan"] = yeni_alan

    rapor["yonlendirme"] = (
        "var"
        if son_url.rstrip("/") != url.rstrip("/")
        else "yok"
    )

    # Sayfa HTML değilse RSS aramasını XML üzerinden yapma.
    icerik_tipi = (
        sonuc["icerik_tipi"] or ""
    ).lower()

    html_icerik = (
        "html" in icerik_tipi
        or b"<html" in sonuc["veri"][:1000].lower()
    )

    besleme_adresleri = []

    if html_icerik:

        html = sonuc["veri"].decode(
            "utf-8",
            errors="replace"
        )

        besleme_adresleri.extend(
            html_beslemelerini_bul(
                html,
                son_url
            )
        )

    # Yaygın RSS yollarını da kontrol et.
    besleme_adresleri.extend(
        olasi_besleme_adresleri(son_url)
    )

    # Aynı adresi ikinci kez deneme.
    besleme_adresleri = list(
        dict.fromkeys(besleme_adresleri)
    )

    # Gereksiz trafik oluşturmamak için sınırlı kontrol.
    for adres in besleme_adresleri[:12]:

        besleme = besleme_kontrol(adres)

        if besleme["durum"] == "rss_atom_gecerli":

            rapor["rss_adresleri"].append(
                besleme["adres"]
            )

        time.sleep(0.2)

    if rapor["rss_adresleri"]:
        rapor["rss_durumu"] = "bulundu"
    else:
        rapor["rss_durumu"] = "bulunamadi"

    # Robots.txt adresini kontrol et.
    rapor["robots"] = robots_kontrol(
        son_url
    )

    return rapor


# ------------------------------------------------------------
# KAYNAK KAYDINA SONUÇLARI İŞLEME
# ------------------------------------------------------------

def kaynak_guncelle(kaynak, rapor):

    kaynak.setdefault("dogrulama", {})

    kaynak["dogrulama"]["adres"] = rapor["erisim"]

    kaynak["dogrulama"]["rss"] = rapor["rss_durumu"]

    kaynak["dogrulama"]["son_kontrol"] = (
        rapor["kontrol_tarihi"]
    )

    kaynak["son_kontrol"] = rapor["kontrol_tarihi"]

    kaynak["kontrol_raporu"] = {
        "http_kodu": rapor["http_kodu"],
        "yonlendirme": rapor["yonlendirme"],
        "son_url": rapor.get("son_url"),
        "eski_alan": rapor["eski_alan"],
        "yeni_alan": rapor["yeni_alan"],
        "rss_adresleri": rapor["rss_adresleri"],
        "rss_durumu": rapor["rss_durumu"],
        "robots_durumu": (
            rapor["robots"]["durum"]
            if rapor.get("robots")
            else "kontrol_edilmedi"
        ),
        "hata": rapor["hata"]
    }

    # Bulunan RSS adreslerini ayrıca sakla.
    kaynak["rss_adresleri"] = (
        rapor["rss_adresleri"]
    )

    # Yönlendirme başka bir alan adına gidiyorsa
    # eski alan adını otomatik değiştirme.
    if (
        rapor.get("yeni_alan")
        and rapor["yeni_alan"] != rapor["eski_alan"]
    ):

        kaynak["alan_dogrulama_uyarisi"] = (
            "Yönlendirme farklı alan adına gidiyor. "
            "Manuel inceleme gerekiyor."
        )

    # Kaynak otomatik aktif yapılmaz.
    if kaynak.get("durum") != "aday":
        kaynak["durum"] = "inceleme_gerekli"

    # İl ve ilçe otomatik kesinleştirilmez.
    kaynak.setdefault("dogrulama", {})

    kaynak["dogrulama"].setdefault(
        "il",
        "manuel_dogrulama_gerekli"
    )

    kaynak["dogrulama"].setdefault(
        "ilce",
        "manuel_dogrulama_gerekli"
    )

    return kaynak


# ------------------------------------------------------------
# KONTROL SIRASINI OLUŞTURMA
# ------------------------------------------------------------

def kontrol_sirasi(kaynaklar):

    sirali = []

    for i, kaynak in enumerate(kaynaklar):

        if not isinstance(kaynak, dict):
            continue

        if not kaynak.get("url"):
            continue

        sirali.append(i)

    return sirali


# ------------------------------------------------------------
# ANA PROGRAM
# ------------------------------------------------------------

def ana():

    print("=" * 60)
    print("MİHVER KAYNAK DOĞRULAMA MOTORU")
    print("=" * 60)

    veri = json_oku(
        KAYNAK_DOSYASI,
        {
            "iller": [],
            "kaynaklar": []
        }
    )

    if not isinstance(veri, dict):
        raise ValueError(
            "kaynaklar.json biçimi geçersiz."
        )

    if not isinstance(
        veri.get("kaynaklar"),
        list
    ):
        raise ValueError(
            "kaynaklar alanı liste değil."
        )

    durum = json_oku(
        DURUM_DOSYASI,
        {"sira": 0}
    )

    kaynaklar = veri["kaynaklar"]

    sirali = kontrol_sirasi(
        kaynaklar
    )

    if not sirali:

        print("Kontrol edilecek URL bulunamadı.")
        return

    sira = int(
        durum.get("sira", 0)
    ) % len(sirali)

    kontrol_edilen = 0
    erisilebilir = 0
    erisilemeyen = 0
    rss_bulunan = 0

    raporlar = []

    print("Toplam URL içeren kaynak:", len(sirali))
    print("Başlangıç sırası:", sira)

    for adim in range(
        min(KONTROL_LIMITI, len(sirali))
    ):

        pozisyon = (sira + adim) % len(sirali)

        kaynak_indeksi = sirali[pozisyon]

        kaynak = kaynaklar[kaynak_indeksi]

        print(
            "\nKontrol:",
            adim + 1,
            "/",
            min(KONTROL_LIMITI, len(sirali))
        )

        print(
            "Kaynak:",
            kaynak.get("ad", "İsimsiz")
        )

        print(
            "URL:",
            kaynak.get("url", "")
        )

        try:

            sonuc = kaynak_kontrol(
                kaynak
            )

            kaynak_guncelle(
                kaynak,
                sonuc
            )

            raporlar.append({
                "kimlik": kaynak.get("kimlik"),
                "ad": kaynak.get("ad"),
                "il": kaynak.get("il"),
                "rapor": sonuc
            })

            kontrol_edilen += 1

            if sonuc["erisim"] == "erisilebilir":
                erisilebilir += 1
            else:
                erisilemeyen += 1

            if sonuc["rss_adresleri"]:
                rss_bulunan += 1

        except Exception as hata:

            print(
                "Kaynak kontrol hatası:",
                str(hata)[:200]
            )

            kaynak.setdefault(
                "dogrulama",
                {}
            )

            kaynak["dogrulama"]["adres"] = (
                "kontrol_hatasi"
            )

        durum["sira"] = (
            pozisyon + 1
        ) % len(sirali)

        durum["son_calisma"] = simdi()

        # Her 5 kaynakta bir kaydet.
        if (adim + 1) % 5 == 0:

            json_yaz(
                KAYNAK_DOSYASI,
                veri
            )

            json_yaz(
                DURUM_DOSYASI,
                durum
            )

        time.sleep(BEKLEME)

    # Son kayıtlar.
    json_yaz(
        KAYNAK_DOSYASI,
        veri
    )

    json_yaz(
        DURUM_DOSYASI,
        durum
    )

    # Çalışma raporu.
    rapor = {
        "tarih": simdi(),
        "toplam_kaynak": len(kaynaklar),
        "url_olan_kaynak": len(sirali),
        "bu_calisma_kontrol_edilen": kontrol_edilen,
        "erisilebilir": erisilebilir,
        "erisilemeyen": erisilemeyen,
        "rss_bulunan": rss_bulunan,
        "sonraki_sira": durum["sira"],
        "sonuclar": raporlar
    }

    json_yaz(
        RAPOR_DOSYASI,
        rapor
    )

    print("\n" + "=" * 60)
    print("KAYNAK KONTROLÜ TAMAMLANDI")
    print("=" * 60)

    print("Kontrol edilen:", kontrol_edilen)
    print("Erişilebilir:", erisilebilir)
    print("Erişilemeyen:", erisilemeyen)
    print("RSS bulunan:", rss_bulunan)
    print("Toplam kaynak:", len(kaynaklar))
    print("Sonraki başlangıç:", durum["sira"])

    print("\nOluşturulan dosyalar:")
    print("- kaynaklar.json")
    print("- dogrulama_durumu.json")
    print("- kaynak_dogrulama_raporu.json")


if __name__ == "__main__":
    ana()
