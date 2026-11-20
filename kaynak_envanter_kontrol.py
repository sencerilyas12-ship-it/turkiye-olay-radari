
import argparse
import ipaddress
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

VARSAYILAN_ENVANTER = "kaynaklar_ek.json"
VARSAYILAN_RAPOR = "kaynak_envanter_kontrol_raporu.json"

ZORUNLU_ALANLAR = [
    "surum", "proje", "ayarlar", "iller",
    "kaynak_turleri", "resmi_dizinler",
    "kaynaklar", "ilce_kapsami",
    "haber_toplama_kapsami", "dogrulama_kurallari",
]

# Envanterdeki varsayılan "aday" durumu özellikle eklendi.
IZINLI_DURUMLAR = {
    "aday", "aktif", "pasif", "beklemede", "devre_disi"
}

MAX_AKTIF_UYARI_DETAYI = 5


class Kontrolcu:
    """MIHVER kaynak envanteri yapısal kontrol sınıfı."""

    def __init__(self):
        self.hatalar = []
        self.uyarilar = []
        self.kontroller = []

    def sifirla(self):
        self.hatalar = []
        self.uyarilar = []
        self.kontroller = []

    def hata(self, mesaj):
        self.hatalar.append(mesaj)

    def uyari(self, mesaj):
        self.uyarilar.append(mesaj)

    def kontrol(self, ad, sonuc, detay=""):
        self.kontroller.append({
            "kontrol": ad,
            "sonuc": "basarili" if sonuc else "basarisiz",
            "detay": detay
        })

    @staticmethod
    def gercek_int(deger):
        return isinstance(deger, int) and not isinstance(deger, bool)

    @staticmethod
    def url_gecerli(url):
        if not isinstance(url, str) or not url.strip():
            return False

        if url != url.strip() or any(c.isspace() for c in url):
            return False

        try:
            p = urlparse(url)
            host = p.hostname
            _ = p.port
        except ValueError:
            return False

        return (
            p.scheme.lower() in ("http", "https")
            and bool(host)
            and not p.username
            and not p.password
        )

    @staticmethod
    def url_ozel_mi(url):
        try:
            host = (urlparse(url).hostname or "").lower()
        except ValueError:
            return True

        if host in ("localhost", "localhost.localdomain"):
            return True

        try:
            ip = ipaddress.ip_address(host)
            return (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_unspecified
            )
        except ValueError:
            return False

    @staticmethod
    def url_normalize(url):
        p = urlparse(url.strip())
        host = (p.hostname or "").lower()
        port = p.port

        if port and not (
            (p.scheme.lower() == "http" and port == 80)
            or (p.scheme.lower() == "https" and port == 443)
        ):
            host = f"{host}:{port}"

        yol = p.path.rstrip("/") or "/"
        return f"{p.scheme.lower()}://{host}{yol}" + (
            f"?{p.query}" if p.query else ""
        )

    def oku(self, yol):
        yol = Path(yol)

        if not yol.exists():
            self.hata(f"{yol.name} dosyası bulunamadı.")
            self.kontrol("JSON dosyası okunabiliyor", False, "Dosya bulunamadı.")
            return None

        try:
            with yol.open("r", encoding="utf-8") as f:
                veri = json.load(f)
        except json.JSONDecodeError as exc:
            self.hata(f"JSON biçim hatası: {exc}")
            self.kontrol("JSON dosyası okunabiliyor", False, str(exc))
            return None
        except Exception as exc:
            self.hata(f"Dosya okunamadı: {exc}")
            self.kontrol("JSON dosyası okunabiliyor", False, str(exc))
            return None

        self.kontrol("JSON dosyası okunabiliyor", True)

        if not isinstance(veri, dict):
            self.hata("Ana veri JSON nesnesi olmalıdır.")
            self.kontrol("Ana veri JSON nesnesi", False)
            return None

        self.kontrol("Ana veri JSON nesnesi", True)
        return veri

    def kontrol_alan_ve_tur(self, veri):
        eksikler = [a for a in ZORUNLU_ALANLAR if a not in veri]

        self.kontrol(
            "Zorunlu alanlar",
            not eksikler,
            ", ".join(eksikler)
        )

        if eksikler:
            self.hata("Eksik alanlar: " + ", ".join(eksikler))

        beklenen = {
            "surum": str,
            "proje": str,
            "ayarlar": dict,
            "dogrulama_kurallari": dict,
            "ilce_kapsami": dict,
            "haber_toplama_kapsami": dict,
            "iller": list,
            "kaynak_turleri": list,
            "resmi_dizinler": list,
            "kaynaklar": list,
        }

        for alan, tip in beklenen.items():
            if alan not in veri:
                continue

            if not isinstance(veri[alan], tip):
                self.hata(
                    f"'{alan}' alanının türü hatalı: "
                    f"{type(veri[alan]).__name__}"
                )
            elif alan in ("surum", "proje") and not veri[alan].strip():
                self.hata(f"'{alan}' alanı boş.")

    def kontrol_iller(self, veri):
        iller = veri.get("iller")

        if not isinstance(iller, list):
            self.hata("İller alanı liste biçiminde değil.")
            self.kontrol("81 il ve plaka kodları", False)
            return

        kodlar = []
        adlar = []

        for sira, il in enumerate(iller):
            if not isinstance(il, dict):
                self.hata(f"İl kaydı #{sira} nesne biçiminde değil.")
                continue

            plaka = il.get("plaka")
            ad = il.get("ad")

            if not self.gercek_int(plaka):
                self.hata(f"İl kaydı #{sira}: plaka tamsayı olmalı.")
            else:
                kodlar.append(plaka)

            if not isinstance(ad, str) or not ad.strip():
                self.hata(f"İl kaydı #{sira}: il adı boş veya hatalı.")
            else:
                adlar.append(ad.strip())

        tamam = (
            len(iller) == 81
            and len(kodlar) == 81
            and set(kodlar) == set(range(1, 82))
            and len(adlar) == 81
            and len(set(adlar)) == 81
        )

        self.kontrol(
            "81 il ve plaka kodları",
            tamam,
            f"Bulunan il kaydı: {len(iller)}"
        )

        if not tamam:
            self.hata(
                "İl listesi 81 benzersiz il ve 1-81 plaka "
                "kodlarından oluşmuyor."
            )

    def kontrol_turler(self, veri):
        turler = veri.get("kaynak_turleri")

        if not isinstance(turler, list) or not turler:
            self.hata("Kaynak türleri listesi boş veya hatalı.")
            self.kontrol("Kaynak türleri listesi", False)
            return set()

        idler = set()

        for tur in turler:
            if isinstance(tur, str) and tur.strip():
                idler.add(tur.strip())
            elif isinstance(tur, dict):
                deger = tur.get("id") or tur.get("ad")
                if isinstance(deger, str) and deger.strip():
                    idler.add(deger.strip())
                else:
                    self.hata("Kaynak türünde id veya ad eksik.")
            else:
                self.hata("Kaynak türü kaydı hatalı.")

        self.kontrol("Kaynak türleri listesi", bool(idler))
        return idler

    def kontrol_dizinler(self, veri):
        dizinler = veri.get("resmi_dizinler")

        if not isinstance(dizinler, list):
            self.hata("Resmî dizinler alanı liste değil.")
            self.kontrol("Resmî dizin kayıtları", False)
            return set()

        ids = []
        baslangic = len(self.hatalar)

        for sira, dizin in enumerate(dizinler):
            if not isinstance(dizin, dict):
                self.hata(f"Resmî dizin kaydı #{sira} hatalı.")
                continue

            dizin_id = dizin.get("id")
            if not isinstance(dizin_id, str) or not dizin_id.strip():
                self.hata(f"Resmî dizin kaydı #{sira}: ID eksik.")
            else:
                ids.append(dizin_id)

            if not self.url_gecerli(dizin.get("url")):
                self.hata(
                    f"Geçersiz resmî dizin adresi: "
                    f"{dizin_id or sira}"
                )

        if len(ids) != len(set(ids)):
            self.hata("Resmî dizinlerde tekrarlı ID var.")

        if not dizinler:
            self.hata("Resmî dizin listesi boş.")

        ok = len(self.hatalar) == baslangic

        self.kontrol(
            "Resmî dizin kayıtları",
            ok,
            f"Dizin sayısı: {len(dizinler)}"
        )

        return set(ids)

    def kontrol_kaynaklar(self, veri, tur_idleri, dizin_idleri):
        kaynaklar = veri.get("kaynaklar")

        if not isinstance(kaynaklar, list):
            self.hata("Kaynak kayıtları liste biçiminde değil.")
            self.kontrol("Kaynak kayıtları", False)
            return 0

        baslangic = len(self.hatalar)
        ids = []
        urller = {}
        aktifler = []

        for sira, kaynak in enumerate(kaynaklar):
            if not isinstance(kaynak, dict):
                self.hata(f"Kaynak kaydı #{sira} nesne biçiminde değil.")
                continue

            kid = kaynak.get("id")
            etiket = kid if kid else f"#{sira}"

            if not isinstance(kid, str) or not kid.strip():
                self.hata(f"Kaynak kaydı #{sira}: ID eksik.")
            else:
                ids.append(kid)

            adres = kaynak.get("url")

            if not self.url_gecerli(adres):
                self.hata(f"Geçersiz kaynak adresi: {etiket}")
            else:
                if self.url_ozel_mi(adres):
                    self.uyari(
                        f"{etiket}: özel veya yerel IP adresi: {adres}"
                    )

                norm = self.url_normalize(adres)

                if norm in urller:
                    self.hata(
                        f"Mükerrer URL: {etiket} ve {urller[norm]}"
                    )
                else:
                    urller[norm] = etiket

            durum = kaynak.get("durum")

            if durum not in IZINLI_DURUMLAR:
                self.hata(
                    f"{etiket}: geçersiz durum değeri {durum!r}."
                )
            elif durum == "aktif":
                aktifler.append(etiket)

            # Eski "tur" ve yeni "kaynak_turu" alanları desteklenir.
            tur = kaynak.get("kaynak_turu", kaynak.get("tur"))

            if tur is None:
                self.uyari(f"{etiket}: kaynak türü alanı yok.")
            elif tur_idleri and tur not in tur_idleri:
                self.hata(
                    f"{etiket}: tanımsız kaynak türü {tur!r}."
                )

            plaka = kaynak.get("plaka")

            if plaka is not None and not (
                self.gercek_int(plaka) and 1 <= plaka <= 81
            ):
                self.hata(f"{etiket}: geçersiz plaka değeri.")

            dizin_ref = kaynak.get("dizin_id")

            if dizin_ref is not None and dizin_ref not in dizin_idleri:
                self.hata(
                    f"{etiket}: bilinmeyen dizin_id {dizin_ref!r}."
                )

        if len(ids) != len(set(ids)):
            self.hata("Kaynak kayıtlarında tekrarlı ID var.")

        if aktifler:
            if len(aktifler) <= MAX_AKTIF_UYARI_DETAYI:
                for aktif in aktifler:
                    self.uyari(
                        f"{aktif} aktif işaretli. İnsan onayı ve "
                        "doğrulaması ayrıca kontrol edilmeli."
                    )
            else:
                self.uyari(
                    f"{len(aktifler)} kaynak aktif işaretli. "
                    "İnsan onayı ve doğrulaması ayrıca kontrol edilmeli."
                )

        self.kontrol(
            "Kaynak kayıtları (ID, URL, tür, durum, referans)",
            len(self.hatalar) == baslangic,
            f"Kaynak sayısı: {len(kaynaklar)}"
        )

        return len(kaynaklar)

    def kontrol_ilce(self, veri):
        ilce = veri.get("ilce_kapsami")

        tamam = (
            isinstance(ilce, dict)
            and ilce.get("ilce_listesi_tamamlandi") is True
        )

        self.kontrol("İlçe listesinin tamamlanma durumu", tamam)

        if not tamam:
            self.uyari(
                "İlçe listesi henüz tek tek eklenmiş ve tamamlanmış değil."
            )

        if isinstance(ilce, dict):
            liste = ilce.get("ilceler")

            if liste is not None and not isinstance(liste, list):
                self.hata("'ilceler' alanı liste biçiminde olmalı.")

    def kontrol_guvenlik(self, veri):
        ayarlar = veri.get("ayarlar")
        dogrulama = veri.get("dogrulama_kurallari")

        ayarlar = ayarlar if isinstance(ayarlar, dict) else {}
        dogrulama = dogrulama if isinstance(dogrulama, dict) else {}

        kurallar = [
            (
                ayarlar.get("mevcut_dosya_degistirilmeyecek") is True,
                "Mevcut dosyaları koruma ayarı açık değil."
            ),
            (
                ayarlar.get("otomatik_aktiflestirme") is False,
                "Otomatik kaynak aktifleştirme kapalı olmalı."
            ),
            (
                ayarlar.get(
                    "adres_dogrulanmadan_haber_toplamaya_baslama"
                ) is True,
                "Doğrulanmamış adreslerden haber toplama engeli true olmalı."
            ),
            (
                dogrulama.get("robots_txt_kontrolu") is True,
                "robots.txt kontrolü zorunlu olmalı."
            ),
            (
                dogrulama.get(
                    "kaynak_aktiflestirme_icin_insan_onayi"
                ) is True,
                "Kaynak aktifleştirme için insan onayı zorunlu olmalı."
            ),
        ]

        guvenlik_hatalari = []

        for ok, mesaj in kurallar:
            if not ok:
                guvenlik_hatalari.append(mesaj)
                self.hata(mesaj)

        self.kontrol(
            "Güvenlik ayarları",
            not guvenlik_hatalari,
            "; ".join(guvenlik_hatalari)
        )

    def calistir(self, envanter_yolu):
        self.sifirla()

        veri = self.oku(envanter_yolu)

        il_sayisi = 0
        dizin_sayisi = 0
        kaynak_sayisi = 0
        surum = None

        if isinstance(veri, dict):
            surum = veri.get("surum")

            self.kontrol_alan_ve_tur(veri)
            self.kontrol_iller(veri)

            tur_idleri = self.kontrol_turler(veri)
            dizin_idleri = self.kontrol_dizinler(veri)

            kaynak_sayisi = self.kontrol_kaynaklar(
                veri, tur_idleri, dizin_idleri
            )

            self.kontrol_ilce(veri)
            self.kontrol_guvenlik(veri)

            il_sayisi = len(veri.get("iller", []))
            dizin_sayisi = len(veri.get("resmi_dizinler", []))

        return {
            "proje": "MIHVER",
            "kontrol_tarihi": datetime.now().astimezone().isoformat(),
            "envanter_surumu": surum,
            "il_sayisi": il_sayisi,
            "resmi_dizin_sayisi": dizin_sayisi,
            "kaynak_sayisi": kaynak_sayisi,
            "kontrol_sayisi": len(self.kontroller),
            "hata_sayisi": len(self.hatalar),
            "uyari_sayisi": len(self.uyarilar),
            "sonuc": "basarili" if not self.hatalar else "hata_var",
            "kontroller": self.kontroller,
            "hatalar": self.hatalar,
            "uyarilar": self.uyarilar
        }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="MIHVER kaynak envanteri kontrolü"
    )

    parser.add_argument("--envanter", default=None)
    parser.add_argument("--rapor", default=None)

    args = parser.parse_args(argv)

    taban = Path(__file__).resolve().parent

    envanter = (
        Path(args.envanter)
        if args.envanter
        else taban / VARSAYILAN_ENVANTER
    )

    rapor_yolu = (
        Path(args.rapor)
        if args.rapor
        else taban / VARSAYILAN_RAPOR
    )

    kontrolcu = Kontrolcu()
    rapor = kontrolcu.calistir(envanter)

    try:
        rapor_yolu.parent.mkdir(parents=True, exist_ok=True)

        with rapor_yolu.open("w", encoding="utf-8") as f:
            json.dump(rapor, f, ensure_ascii=False, indent=2)

    except Exception as exc:
        print("Rapor kaydedilemedi:", exc)
        return 2

    print("\nMİHVER ENVANTER KONTROLÜ TAMAMLANDI")
    print("İl sayısı:", rapor["il_sayisi"])
    print("Resmî dizin:", rapor["resmi_dizin_sayisi"])
    print("Kaynak:", rapor["kaynak_sayisi"])
    print("Kontrol:", rapor["kontrol_sayisi"])
    print("Hata:", rapor["hata_sayisi"])
    print("Uyarı:", rapor["uyari_sayisi"])
    print("Sonuç:", rapor["sonuc"])
    print("Rapor:", rapor_yolu)

    for mesaj in rapor["hatalar"]:
        print("HATA:", mesaj)

    for mesaj in rapor["uyarilar"]:
        print("UYARI:", mesaj)

    return 1 if rapor["hatalar"] else 0


if __name__ == "__main__":
    sys.exit(main())
