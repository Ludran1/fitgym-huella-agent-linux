"""
Wrapper ctypes del ZKFinger SDK nativo (libzkfp.so) — SIN Mono, SIN pythonnet, SIN el
wrapper C# (libzkfpcsharp). pyzkfp crasheaba en Mono (mono_free_lparray al marshallar los
arrays de AcquireFingerprint, bug no resuelto ni en Mono 6.12). Acá llamamos la API C
directo, controlando los buffers nosotros → robusto.

Firmas tomadas del header del SDK (Demo&Doc/c/demo_v2/include/libzkfp.h):
  int    ZKFPM_Init();
  int    ZKFPM_Terminate();
  int    ZKFPM_GetDeviceCount();
  HANDLE ZKFPM_OpenDevice(int index);                 // HANDLE = void*
  int    ZKFPM_CloseDevice(HANDLE);
  int    ZKFPM_GetParameters(HANDLE, int code, uchar* val, uint* size);  // code 1=width 2=height
  int    ZKFPM_AcquireFingerprint(HANDLE, uchar* img, uint cbImg, uchar* tmpl, uint* cbTmpl);
  HANDLE ZKFPM_DBInit();
  int    ZKFPM_DBFree(HANDLE);
  int    ZKFPM_DBMerge(HANDLE, uchar* t1, uchar* t2, uchar* t3, uchar* reg, uint* cbReg);
  int    ZKFPM_DBAdd(HANDLE, uint fid, uchar* tmpl, uint cbTmpl);
  int    ZKFPM_DBDel(HANDLE, uint fid);
  int    ZKFPM_DBClear(HANDLE);
  int    ZKFPM_DBIdentify(HANDLE, uchar* tmpl, uint cbTmpl, uint* FID, uint* score);
ZKFP_ERR_OK = 0.

Requiere LD_LIBRARY_PATH apuntando a SDK/lib-x64 (el caller se re-ejecuta con eso).
"""
import ctypes as C

ZKFP_ERR_OK = 0
MAX_TEMPLATE_SIZE = 2048
_DEFAULT_IMG = 640 * 480  # buffer holgado por si falla la query de width/height


class ZKFPError(Exception):
    pass


class ZKFP:
    def __init__(self):
        lib = C.CDLL("libzkfp.so")
        self.lib = lib
        vp, i, u, cp = C.c_void_p, C.c_int, C.c_uint, C.c_char_p
        pu = C.POINTER(C.c_uint)

        # restype/argtypes — HANDLE = void* = c_void_p (64-bit). Sin esto ctypes asume int
        # de 32 bits y TRUNCA el puntero del device/db → segfault.
        for name, res, args in [
            ("ZKFPM_Init", i, []),
            ("ZKFPM_Terminate", i, []),
            ("ZKFPM_GetDeviceCount", i, []),
            ("ZKFPM_OpenDevice", vp, [i]),
            ("ZKFPM_CloseDevice", i, [vp]),
            ("ZKFPM_GetParameters", i, [vp, i, cp, pu]),
            ("ZKFPM_AcquireFingerprint", i, [vp, cp, u, cp, pu]),
            ("ZKFPM_DBInit", vp, []),
            ("ZKFPM_DBFree", i, [vp]),
            ("ZKFPM_DBMerge", i, [vp, cp, cp, cp, cp, pu]),
            ("ZKFPM_DBAdd", i, [vp, u, cp, u]),
            ("ZKFPM_DBDel", i, [vp, u]),
            ("ZKFPM_DBClear", i, [vp]),
            ("ZKFPM_DBIdentify", i, [vp, cp, u, pu, pu]),
        ]:
            fn = getattr(lib, name)
            fn.restype = res
            fn.argtypes = args

        self.dev = None
        self.db = None
        self.img_size = _DEFAULT_IMG

    def init(self):
        rc = self.lib.ZKFPM_Init()
        if rc != ZKFP_ERR_OK:
            raise ZKFPError(f"ZKFPM_Init rc={rc}")

    def device_count(self):
        return self.lib.ZKFPM_GetDeviceCount()

    def open(self, index=0):
        self.dev = self.lib.ZKFPM_OpenDevice(index)
        if not self.dev:
            raise ZKFPError("ZKFPM_OpenDevice devolvió NULL (¿lector conectado?)")
        w, h = self._param_int(1), self._param_int(2)
        if w and h:
            self.img_size = max(w * h, 1)
        self.db = self.lib.ZKFPM_DBInit()
        if not self.db:
            raise ZKFPError("ZKFPM_DBInit devolvió NULL")
        return w, h

    def _param_int(self, code):
        buf = C.create_string_buffer(4)
        size = C.c_uint(4)
        rc = self.lib.ZKFPM_GetParameters(self.dev, code, buf, C.byref(size))
        if rc != ZKFP_ERR_OK:
            return 0
        return int.from_bytes(buf.raw[:4], "little")

    def acquire(self):
        """Captura un template. Devuelve bytes si hay dedo, None si no (rc != OK)."""
        img = C.create_string_buffer(self.img_size)
        tmpl = C.create_string_buffer(MAX_TEMPLATE_SIZE)
        size = C.c_uint(MAX_TEMPLATE_SIZE)
        rc = self.lib.ZKFPM_AcquireFingerprint(
            self.dev, img, C.c_uint(self.img_size), tmpl, C.byref(size))
        if rc != ZKFP_ERR_OK:
            return None
        return tmpl.raw[:size.value]

    def merge(self, t1, t2, t3):
        reg = C.create_string_buffer(MAX_TEMPLATE_SIZE)
        size = C.c_uint(MAX_TEMPLATE_SIZE)
        rc = self.lib.ZKFPM_DBMerge(self.db, t1, t2, t3, reg, C.byref(size))
        if rc != ZKFP_ERR_OK:
            raise ZKFPError(f"ZKFPM_DBMerge rc={rc}")
        return reg.raw[:size.value]

    def db_add(self, fid, tmpl):
        rc = self.lib.ZKFPM_DBAdd(self.db, fid, tmpl, len(tmpl))
        if rc != ZKFP_ERR_OK:
            raise ZKFPError(f"ZKFPM_DBAdd rc={rc}")

    def db_clear(self):
        self.lib.ZKFPM_DBClear(self.db)

    def identify(self, tmpl):
        """1:N contra la DB en memoria. Devuelve (fid, score) o None si no matchea."""
        fid, score = C.c_uint(0), C.c_uint(0)
        rc = self.lib.ZKFPM_DBIdentify(self.db, tmpl, len(tmpl), C.byref(fid), C.byref(score))
        if rc != ZKFP_ERR_OK:
            return None
        return fid.value, score.value

    def close(self):
        if self.db:
            self.lib.ZKFPM_DBFree(self.db)
            self.db = None
        if self.dev:
            self.lib.ZKFPM_CloseDevice(self.dev)
            self.dev = None
        self.lib.ZKFPM_Terminate()
