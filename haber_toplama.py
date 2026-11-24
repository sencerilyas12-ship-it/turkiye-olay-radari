
import json
import time
import hashlib
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET

from pathlib import Path
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime


BASE = Path(__file__).resolve().parent

DOSYALAR = {
    "iller": BASE / "ilceler.json",
    "haberler": BASE / "haberler.json",
    "durum": BASE / "tarama_durumu.json",
}

USER_AGENT = "MIHVER-Turkiye-Olay-Radari/6.0"
TIMEOUT = 15
MAKS_SORGU = 80
HABER_SURESI_SAAT = 24
BEKLEME = 0.2

KATEGORILER = {
    "Gündem": "son dakika gündem",
    "Siyaset": "siyaset hükümet meclis parti",
    "Ekonomi": "ekonomi piyasa enflasyon şirket",
    "Asayiş": "asayiş polis jandarma operasyon",
    "Adliye": "mahkeme duruşma savcılık adliye",
    "Soruşturma": "soruşturma gözaltı tutuklama tahliye",
    "Belediye": "belediye yerel yönetim meclis",
    "Eğitim": "okul üniversite eğitim öğretmen",
    "Sağlık": "sağlık hastane doktor",
    "Spor": "spor futbol basketbol",
    "Teknoloji": "teknoloji bilim yapay zeka",
    "Kültür Sanat": "kültür sanat sinema tiyatro",
    "Ulaşım": "ulaşım trafik metro otobüs",
    "Kaza": "trafik kazası iş kazası yaralı",
    "Afet": "deprem sel yangın fırtına",
    "Uyuşturucu": "uyuşturucu operasyonu ele geçirildi",
    "Cinayet": "cinayet öldürüldü şüpheli ölüm",
    "Dolandırıcılık": "dolandırıcılık sahtecilik",
    "Yolsuzluk": "yolsuzluk rüşvet usulsüzlük",
    "Çevre": "çevre kirliliği orman",
    "Tarım": "tarım çiftçi hayvancılık",
    "Turizm": "turizm otel tatil",
    "Dış Haberler": "dünya uluslararası haberler",
    "Savunma": "savunma sanayi askeri güvenlik",
    "Çalışma Hayatı": "işçi emekli istihdam",
    "Vatandaş": "vatandaş mağduriyet şikayet"
}


def simdi():
    return datetime.now(timezone.utc)


def json_oku(yol, varsayilan):
    try:
        with yol.open("r", encoding="utf-8") as dosya:
            return json.load(dosya)
    except (OSError, json.JSONDecodeError):
        return varsayilan


def json_yaz(yol, veri):
    gecici = yol.with_suffix(".tmp")

    with gecici.open("w", encoding="utf-8") as dosya:
        json.dump(veri, dosya, ensure_ascii=False, indent=2)

    gecici.replace(yol)


def tarih_coz(deger):
    if not deger:
        return None

    try:
        tarih = parsedate_to_datetime(deger)

        if tarih.tzinfo is None:
            tarih = tarih.replace(tzinfo=timezone.utc)

        return tarih.astimezone(timezone.utc)

    except (TypeError, ValueError, OverflowError):
        try:
            tarih = datetime.fromisoformat(
                deger.replace("Z", "+00:00")
            )

            if tarih.tzinfo is None:
                tarih = tarih.replace(tzinfo=timezone.utc)

            return tarih.astimezone(timezone.utc)

        except (TypeError, ValueError):
            return None


def konumlari_yukle():
    veri = json_oku(DOSYALAR["iller"], {})

    iller = veri.get("cities", [])
    ilceler = veri.get("districts", [])

    if not isinstance(iller, list) or not isinstance(ilceler, list):
        raise RuntimeError("ilceler.json biçimi hatalı.")

    konumlar = []

    for il in iller:
        il_adi = str(il.get("name", "")).strip()

        if not il_adi:
            continue

        il_id = il.get("Id")

        eslesenler = [
            ilce for ilce in ilceler
            if ilce.get("cityId") == il_id
        ]

        if eslesenler:
            for ilce in eslesenler:
                ilce_adi = str(ilce.get("name", "")).strip()

                if ilce_adi:
                    konumlar.append((il_adi, ilce_adi))
        else:
            konumlar.append((il_adi, ""))

    if not konumlar:
        raise RuntimeError("Hiçbir il bulunamadı.")

    return konumlar


def sorgulari_olustur(konumlar):
    sorgular = []

    for il, ilce in konumlar:
        for kategori, kelimeler in KATEGORILER.items():
            if ilce:
                sorgu = f'"{ilce}" "{il}" {kelimeler}'
            else:
                sorgu = f'"{il}" {kelimeler}'

            sorgular.append({
                "il": il,
                "ilce": ilce,
                "kategori": kategori,
                "sorgu": sorgu
            })

    # Türkiye geneli haberleri de ayrıca tara.
    for kategori, kelimeler in KATEGORILER.items():
        sorgular.append({
            "il": "Türkiye",
            "ilce": "",
            "kategori": kategori,
            "sorgu": kelimeler
        })

    return sorgular


def rss_getir(sorgu):
    adres = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(sorgu)
        + "&hl=tr&gl=TR&ceid=TR:tr"
    )

    istek = urllib.request.Request(
        adres,
        headers={"User-Agent": USER_AGENT}
    )

    try:
        with urllib.request.urlopen(
            istek,
            timeout=TIMEOUT
        ) as cevap:
            return ET.fromstring(cevap.read())

    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        ET.ParseError,
        TimeoutError,
        OSError
    ) as hata:
        print("RSS erişim hatası:", hata)
        return None


def kimlik_uret(link):
    return hashlib.sha256(
        link.encode("utf-8")
    ).hexdigest()


def haberleri_oku(kok, sorgu):
    bulunan = []

    if kok is None:
        return bulunan

    for oge in kok.findall("./channel/item"):
        baslik = oge.findtext("title", "").strip()
        link = oge.findtext("link", "").strip()
        aciklama = oge.findtext("description", "").strip()
        pub_date = oge.findtext("pubDate", "").strip()

        if not baslik or not link:
            continue

        tarih = tarih_coz(pub_date)

        if tarih is None:
            continue

        if tarih < simdi() - timedelta(
            hours=HABER_SURESI_SAAT
        ):
            continue

        kaynak_oge = oge.find("source")

        kaynak = (
            kaynak_oge.text.strip()
            if kaynak_oge is not None and kaynak_oge.text
            else "Google Haberler"
        )

        bulunan.append({
            "kimlik": kimlik_uret(link),
            "baslik": baslik,
            "aciklama": aciklama,
            "link": link,
            "kaynak": kaynak,
            "il": sorgu["il"],
            "ilce": sorgu["ilce"],
            "kategori": sorgu["kategori"],
            "tarih": tarih.isoformat(),
            "toplanma_tarihi": simdi().isoformat(),
            "durum": "Kaynak kontrolü gerekli",
            "yayinda": True
        })

    return bulunan


def haberleri_temizle(haberler):
    sinir = simdi() - timedelta(
        hours=HABER_SURESI_SAAT
    )

    sonuc = []

    for haber in haberler:
        tarih = tarih_coz(
            haber.get("tarih")
            or haber.get("toplanma_tarihi")
        )

        if tarih and tarih >= sinir:
            sonuc.append(haber)

    return sonuc


def ana():
    konumlar = konumlari_yukle()
    sorgular = sorgulari_olustur(konumlar)

    haberler = json_oku(DOSYALAR["haberler"], [])
    durum = json_oku(DOSYALAR["durum"], {})

    if not isinstance(haberler, list):
        haberler = []

    if not isinstance(durum, dict):
        durum = {}

    haberler = haberleri_temizle(haberler)

    mevcut = {
        haber.get("kimlik") or kimlik_uret(haber.get("link", ""))
        for haber in haberler
        if haber.get("link")
    }

    imlec = int(durum.get("sorgu_imleci", 0))
    imlec %= len(sorgular)

    secilenler = []

    adet = min(MAKS_SORGU, len(sorgular))

    for i in range(adet):
        secilenler.append(
            sorgular[(imlec + i) % len(sorgular)]
        )

    yeni = 0
    basarili = 0
    hatali = 0

    for sira, sorgu in enumerate(secilenler, start=1):
        print(
            f"{sira}/{len(secilenler)} "
            f"{sorgu['il']} {sorgu['ilce']} "
            f"{sorgu['kategori']}"
        )

        kok = rss_getir(sorgu["sorgu"])

        if kok is None:
            hatali += 1
            continue

        basarili += 1

        for haber in haberleri_oku(kok, sorgu):
            kimlik = haber["kimlik"]

            if kimlik in mevcut:
                continue

            haberler.append(haber)
            mevcut.add(kimlik)
            yeni += 1

        time.sleep(BEKLEME)

    durum["sorgu_imleci"] = (
        imlec + len(secilenler)
    ) % len(sorgular)

    durum["son_tarama"] = simdi().isoformat()
    durum["toplam_sorgu"] = len(sorgular)
    durum["son_calismada_yeni_haber"] = yeni
    durum["son_calismada_basarili_sorgu"] = basarili
    durum["son_calismada_hatali_sorgu"] = hatali

    haberler = haberleri_temizle(haberler)

    haberler.sort(
        key=lambda x: x.get("tarih", ""),
        reverse=True
    )

    json_yaz(DOSYALAR["haberler"], haberler)
    json_yaz(DOSYALAR["durum"], durum)

    print("Tarama tamamlandı.")
    print("İl/ilçe konumu:", len(konumlar))
    print("Toplam sorgu:", len(sorgular))
    print("Bu çalışmada taranan:", len(secilenler))
    print("Başarılı sorgu:", basarili)
    print("Hatalı sorgu:", hatali)
    print("Yeni haber:", yeni)
    print("Arşivdeki haber:", len(haberler))


if __name__ == "__main__":
    ana()
