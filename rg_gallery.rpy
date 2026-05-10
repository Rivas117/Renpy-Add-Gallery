# -*- coding: utf-8 -*-
# rg_gallery_compat_rewrite.rpy
# Galería drop-in para Ren'Py con enfoque conservador de compatibilidad.
# Copiar dentro de game/

init -20 python:
    import os

    try:
        basestring
    except NameError:
        basestring = str

    # ------------------------------------------------------------
    # Configuración básica
    # ------------------------------------------------------------
    RGC_GALLERY_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")
    RGC_GALLERY_VID_EXTS = (".webm", ".ogv", ".mp4", ".avi", ".mpeg", ".mpg", ".mkv")

    RGC_GALLERY_PREFERRED_PREFIXES = (
        "images/", "image/", "cg/", "cgs/", "art/",
        "backgrounds/", "background/", "bg/", "bgs/",
        "movies/", "movie/", "videos/", "video/"
    )

    RGC_GALLERY_EXCLUDED_PREFIXES = (
        "gui/",
        "cache/",
        "renpy/common/",
        "common/",
        "tl/",
        "renpy_add_galery/",
        "renpy_add_gallery/",
    )

    # Estado global simple para máxima compatibilidad.
    rgc_gallery_filter_kind = "img"   # img | vid | all
    rgc_gallery_page = 0
    rgc_gallery_view_index = 0

    # Cachés
    rgc_gallery_all_files = []
    rgc_gallery_lower_to_real = {}
    rgc_gallery_image_files = []
    rgc_gallery_video_files = []
    rgc_gallery_all_items = []
    rgc_gallery_video_thumb = {}
    rgc_gallery_video_disp = {}

    def rgc_gallery_log(msg):
        try:
            renpy.log("[rg_gallery] %s" % msg)
        except Exception:
            pass

    def rgc_gallery_norm(path):
        if not path:
            return ""
        try:
            path = path.replace("\\", "/")
        except Exception:
            return ""
        while "//" in path:
            path = path.replace("//", "/")
        return path

    def rgc_gallery_list_files():
        try:
            files = renpy.list_files()
        except Exception:
            files = []
        out = []
        for fn in files:
            n = rgc_gallery_norm(fn)
            if n:
                out.append(n)
        return out

    def rgc_gallery_build_index():
        global rgc_gallery_all_files
        global rgc_gallery_lower_to_real

        rgc_gallery_all_files = rgc_gallery_list_files()
        rgc_gallery_lower_to_real = {}

        for fn in rgc_gallery_all_files:
            lfn = fn.lower()
            if lfn not in rgc_gallery_lower_to_real:
                rgc_gallery_lower_to_real[lfn] = fn

    def rgc_gallery_real_path(path):
        p = rgc_gallery_norm(path)
        if not p:
            return None

        lfn = p.lower()
        real = rgc_gallery_lower_to_real.get(lfn, None)
        if real:
            return real

        try:
            if renpy.loadable(p):
                return p
        except Exception:
            pass

        return None

    def rgc_gallery_is_allowed(path):
        lfn = path.lower()

        for p in RGC_GALLERY_EXCLUDED_PREFIXES:
            if lfn.startswith(p):
                return False

        return True

    def rgc_gallery_collect(exts):
        preferred = []
        fallback = []

        for fn in rgc_gallery_all_files:
            lfn = fn.lower()

            good_ext = False
            for ext in exts:
                if lfn.endswith(ext):
                    good_ext = True
                    break
            if not good_ext:
                continue

            if not rgc_gallery_is_allowed(fn):
                continue

            if not rgc_gallery_real_path(fn):
                continue

            is_preferred = False
            for p in RGC_GALLERY_PREFERRED_PREFIXES:
                if lfn.startswith(p):
                    is_preferred = True
                    break

            if is_preferred:
                preferred.append(fn)
            else:
                fallback.append(fn)

        files = preferred if preferred else fallback

        dedup = {}
        for fn in files:
            dedup[fn.lower()] = fn

        out = list(dedup.values())
        out.sort(key=lambda s: s.lower())
        return out

    def rgc_gallery_find_video_thumb(video_path):
        base, _ext = os.path.splitext(video_path)
        candidates = []

        for e in RGC_GALLERY_IMG_EXTS:
            candidates.append(base + e)
        for e in RGC_GALLERY_IMG_EXTS:
            candidates.append(base + "_thumb" + e)
        for e in RGC_GALLERY_IMG_EXTS:
            candidates.append(base + "_preview" + e)
        for e in RGC_GALLERY_IMG_EXTS:
            candidates.append(base + "_poster" + e)
        for e in RGC_GALLERY_IMG_EXTS:
            candidates.append(base + "_cover" + e)

        for c in candidates:
            real = rgc_gallery_real_path(c)
            if real:
                return real

        return None

    def rgc_gallery_refresh():
        global rgc_gallery_image_files
        global rgc_gallery_video_files
        global rgc_gallery_all_items
        global rgc_gallery_video_thumb
        global rgc_gallery_video_disp

        rgc_gallery_build_index()
        rgc_gallery_image_files = rgc_gallery_collect(RGC_GALLERY_IMG_EXTS)
        rgc_gallery_video_files = rgc_gallery_collect(RGC_GALLERY_VID_EXTS)

        rgc_gallery_all_items = []
        for fn in rgc_gallery_image_files:
            rgc_gallery_all_items.append(("img", fn))
        for fn in rgc_gallery_video_files:
            rgc_gallery_all_items.append(("vid", fn))

        rgc_gallery_all_items.sort(key=lambda t: t[1].lower())

        rgc_gallery_video_thumb = {}
        for fn in rgc_gallery_video_files:
            rgc_gallery_video_thumb[fn] = rgc_gallery_find_video_thumb(fn)

        rgc_gallery_video_disp = {}

    def rgc_gallery_filtered_items(kind=None):
        if kind is None:
            kind = rgc_gallery_filter_kind

        if kind == "img":
            return [("img", f) for f in rgc_gallery_image_files]
        elif kind == "vid":
            return [("vid", f) for f in rgc_gallery_video_files]
        else:
            return list(rgc_gallery_all_items)

    def rgc_gallery_get_thumb_size():
        w = int(getattr(config, "screen_width", 1280) or 1280)
        h = int(getattr(config, "screen_height", 720) or 720)

        if w <= 960 or h <= 640:
            return (180, 102)
        elif w <= 1280:
            return (220, 124)
        return (240, 135)

    def rgc_gallery_get_grid():
        thumb_w, thumb_h = rgc_gallery_get_thumb_size()
        sw = int(getattr(config, "screen_width", 1280) or 1280)
        sh = int(getattr(config, "screen_height", 720) or 720)

        usable_w = max(320, int(sw * 0.94) - 120)
        usable_h = max(220, int(sh * 0.94) - 250)

        cols = usable_w // max(1, thumb_w + 10)
        rows = usable_h // max(1, thumb_h + 12)

        if cols < 3:
            cols = 3
        if cols > 8:
            cols = 8
        if rows < 2:
            rows = 2
        if rows > 6:
            rows = 6

        return cols, rows, thumb_w, thumb_h

    def rgc_gallery_items_per_page(kind=None):
        cols, rows, _tw, _th = rgc_gallery_get_grid()
        return max(1, cols * rows)

    def rgc_gallery_total_pages(kind=None):
        items = rgc_gallery_filtered_items(kind)
        per_page = rgc_gallery_items_per_page(kind)
        return max(1, (len(items) + per_page - 1) // per_page)

    def rgc_gallery_page_items(kind=None, page=None):
        if kind is None:
            kind = rgc_gallery_filter_kind
        if page is None:
            page = rgc_gallery_page

        items = rgc_gallery_filtered_items(kind)
        per_page = rgc_gallery_items_per_page(kind)
        total_pages = max(1, (len(items) + per_page - 1) // per_page)

        if page < 0:
            page = 0
        if page >= total_pages:
            page = total_pages - 1

        start = page * per_page
        end = min(len(items), start + per_page)
        return items[start:end]

    def rgc_gallery_open(kind=None):
        global rgc_gallery_filter_kind
        global rgc_gallery_page

        if kind in ("img", "vid", "all"):
            rgc_gallery_filter_kind = kind

        rgc_gallery_refresh()
        rgc_gallery_page = 0

    def rgc_gallery_set_filter(kind):
        global rgc_gallery_filter_kind
        global rgc_gallery_page

        if kind not in ("img", "vid", "all"):
            kind = "img"

        rgc_gallery_filter_kind = kind
        rgc_gallery_page = 0
        renpy.restart_interaction()

    def rgc_gallery_set_page(page):
        global rgc_gallery_page
        total = rgc_gallery_total_pages()
        if page < 0:
            page = 0
        if page >= total:
            page = total - 1
        rgc_gallery_page = page
        renpy.restart_interaction()

    def rgc_gallery_page_delta(delta):
        rgc_gallery_set_page(rgc_gallery_page + delta)

    def rgc_gallery_open_viewer(index):
        global rgc_gallery_view_index
        items = rgc_gallery_filtered_items()
        if not items:
            return
        if index < 0:
            index = 0
        if index >= len(items):
            index = len(items) - 1
        rgc_gallery_view_index = index
        renpy.show_screen("rgc_gallery_viewer")
        renpy.restart_interaction()

    def rgc_gallery_close_viewer():
        renpy.hide_screen("rgc_gallery_viewer")
        renpy.restart_interaction()

    def rgc_gallery_view_delta(delta):
        global rgc_gallery_view_index
        items = rgc_gallery_filtered_items()
        total = len(items)
        if total <= 0:
            rgc_gallery_view_index = 0
            return
        rgc_gallery_view_index = (rgc_gallery_view_index + delta) % total
        renpy.restart_interaction()

    def rgc_gallery_current_item():
        items = rgc_gallery_filtered_items()
        if not items:
            return None

        idx = rgc_gallery_view_index
        if idx < 0:
            idx = 0
        if idx >= len(items):
            idx = len(items) - 1
        return items[idx]

    def rgc_gallery_movie(video_path):
        if not video_path:
            return None

        real = rgc_gallery_real_path(video_path)
        if not real:
            return None

        cached = rgc_gallery_video_disp.get(real, None)
        if cached is not None:
            return cached

        poster = rgc_gallery_video_thumb.get(real, None)

        try:
            disp = Movie(play=real, loop=True, image=poster)
        except Exception:
            try:
                disp = Movie(play=real, loop=True)
            except Exception:
                disp = None

        rgc_gallery_video_disp[real] = disp
        return disp

    def rgc_gallery_scaled(source, max_w, max_h):
        if source is None:
            return None

        # En ramas nuevas.
        try:
            return Transform(source, fit="contain", xsize=max_w, ysize=max_h)
        except Exception:
            pass

        # En ramas viejas / compatibilidad.
        try:
            return Transform(source, xmaximum=max_w, ymaximum=max_h)
        except Exception:
            pass

        try:
            return Transform(source)
        except Exception:
            pass

        return source

    def rgc_gallery_preview_displayable(kind, fn):
        if not fn:
            return Solid("#222")

        if kind == "img":
            real = rgc_gallery_real_path(fn)
            if real:
                return real
            return Solid("#222")

        thumb = rgc_gallery_video_thumb.get(fn, None)
        if thumb:
            return thumb

        return Solid("#222")

    rgc_gallery_refresh()


init 999 python:
    try:
        if "rgc_gallery_entry" not in config.overlay_screens:
            config.overlay_screens.append("rgc_gallery_entry")
    except Exception:
        pass

    try:
        if hasattr(config, "always_shown_screens"):
            if "rgc_gallery_entry" not in config.always_shown_screens:
                config.always_shown_screens.append("rgc_gallery_entry")
    except Exception:
        pass

    try:
        if hasattr(config, "context_copy_remove_screens"):
            if "rgc_gallery_viewer" not in config.context_copy_remove_screens:
                config.context_copy_remove_screens.append("rgc_gallery_viewer")
    except Exception:
        pass


screen rgc_gallery_entry():
    layer "overlay"
    zorder 9998

    key "K_F8" action [Function(rgc_gallery_open), ShowMenu("rgc_gallery")]

    $ rgc_in_any_menu = False
    if main_menu:
        $ rgc_in_any_menu = True
    elif renpy.get_screen("main_menu"):
        $ rgc_in_any_menu = True
    elif renpy.get_screen("navigation"):
        $ rgc_in_any_menu = True
    elif renpy.get_screen("game_menu"):
        $ rgc_in_any_menu = True

    if rgc_in_any_menu:
        frame:
            background Solid("#0008")
            padding (10, 8)
            xalign 0.98
            yalign 0.98

            hbox:
                spacing 10
                text "F8"
                textbutton "Galería" action [Function(rgc_gallery_open), ShowMenu("rgc_gallery")]


screen rgc_gallery_viewer():
    modal True
    layer "screens"
    zorder 10000

    $ rgc_items = rgc_gallery_filtered_items()
    $ rgc_total = len(rgc_items)
    $ rgc_idx = rgc_gallery_view_index
    if rgc_idx < 0:
        $ rgc_idx = 0
    if rgc_total > 0 and rgc_idx >= rgc_total:
        $ rgc_idx = rgc_total - 1
    $ rgc_item = (rgc_items[rgc_idx] if rgc_total > 0 else None)
    $ rgc_kind = (rgc_item[0] if rgc_item else None)
    $ rgc_fn = (rgc_item[1] if rgc_item else None)
    $ rgc_display_pos = (rgc_idx + 1) if rgc_total > 0 else 0
    $ rgc_status_text = ("Elemento %d/%d   (←/→, rueda, clic lados, Esc)" % (rgc_display_pos, rgc_total)) if rgc_total > 0 else "Elemento 0/0"

    key "K_ESCAPE" action Function(rgc_gallery_close_viewer)
    key "K_RIGHT" action Function(rgc_gallery_view_delta, 1)
    key "K_LEFT" action Function(rgc_gallery_view_delta, -1)
    key "mousedown_4" action Function(rgc_gallery_view_delta, -1)
    key "mousedown_5" action Function(rgc_gallery_view_delta, 1)

    button:
        xfill True
        yfill True
        background Solid("#0000")
        action Function(rgc_gallery_close_viewer)

    add Solid("#000c")

    frame:
        xalign 0.5
        yalign 0.5
        xsize int((config.screen_width or 1280) * 0.92)
        ysize int((config.screen_height or 720) * 0.90)
        padding (16, 16)
        background Solid("#111e")

        vbox:
            spacing 10

            hbox:
                xfill True
                spacing 10

                if rgc_fn:
                    text "[rgc_fn]" size 18 xmaximum int((config.screen_width or 1280) * 0.78)
                else:
                    text "Galería" size 18

                null width 10

                textbutton "X":
                    xalign 1.0
                    text_size 26
                    action Function(rgc_gallery_close_viewer)

            frame:
                xfill True
                yfill True
                padding (10, 10)
                background Solid("#0008")

                fixed:
                    xfill True
                    yfill True

                    if not rgc_fn:
                        text "Nada que mostrar." xalign 0.5 yalign 0.5
                    else:
                        $ rgc_view_w = int((config.screen_width or 1280) * 0.84)
                        $ rgc_view_h = int((config.screen_height or 720) * 0.70)

                        if rgc_kind == "img":
                            add rgc_gallery_scaled(rgc_fn, rgc_view_w, rgc_view_h) xalign 0.5 yalign 0.5
                        else:
                            $ rgc_mv = rgc_gallery_movie(rgc_fn)
                            if rgc_mv:
                                add rgc_gallery_scaled(rgc_mv, rgc_view_w, rgc_view_h) xalign 0.5 yalign 0.5
                            else:
                                $ rgc_thumb = rgc_gallery_video_thumb.get(rgc_fn, None)
                                if rgc_thumb:
                                    add rgc_gallery_scaled(rgc_thumb, rgc_view_w, rgc_view_h) xalign 0.5 yalign 0.5
                                    text "▶" size 80 xalign 0.5 yalign 0.5
                                else:
                                    text "Video no disponible para mostrar." xalign 0.5 yalign 0.5

                    hbox:
                        xfill True
                        yfill True

                        button:
                            xfill True
                            yfill True
                            background Solid("#0000")
                            hover_background Solid("#0000")
                            action Function(rgc_gallery_view_delta, -1)

                        button:
                            xfill True
                            yfill True
                            background Solid("#0000")
                            hover_background Solid("#0000")
                            action Function(rgc_gallery_view_delta, 1)

            hbox:
                xalign 0.5
                spacing 18

                textbutton "<":
                    text_size 30
                    sensitive rgc_total > 1
                    action Function(rgc_gallery_view_delta, -1)

                text rgc_status_text size 18

                textbutton ">":
                    text_size 30
                    sensitive rgc_total > 1
                    action Function(rgc_gallery_view_delta, 1)


screen rgc_gallery():
    tag menu

    key "K_PAGEUP" action Function(rgc_gallery_page_delta, -1)
    key "K_PAGEDOWN" action Function(rgc_gallery_page_delta, 1)

    $ rgc_items = rgc_gallery_filtered_items()
    $ rgc_cols, rgc_rows, rgc_thumb_w, rgc_thumb_h = rgc_gallery_get_grid()
    $ rgc_per_page = max(1, rgc_cols * rgc_rows)
    $ rgc_total_pages = rgc_gallery_total_pages()
    $ rgc_page = rgc_gallery_page
    if rgc_page < 0:
        $ rgc_page = 0
    if rgc_page >= rgc_total_pages:
        $ rgc_page = rgc_total_pages - 1
    $ rgc_start = rgc_page * rgc_per_page
    $ rgc_page_items = rgc_gallery_page_items()
    $ rgc_img_count = len(rgc_gallery_image_files)
    $ rgc_vid_count = len(rgc_gallery_video_files)
    $ rgc_all_count = len(rgc_gallery_all_items)
    $ rgc_img_label = "Imágenes (%d)" % rgc_img_count
    $ rgc_vid_label = "Videos (%d)" % rgc_vid_count
    $ rgc_all_label = "Todo (%d)" % rgc_all_count
    $ rgc_page_label = "Página %d/%d   (PageUp/PageDown)" % (rgc_page + 1, rgc_total_pages)

    add Solid("#000a")

    frame:
        xalign 0.5
        yalign 0.5
        xsize int((config.screen_width or 1280) * 0.94)
        ysize int((config.screen_height or 720) * 0.94)
        padding (18, 18)

        vbox:
            spacing 12

            hbox:
                xfill True
                spacing 10

                text "Galería" size 40 bold True
                text "  (F8 abre la galería)" size 18

                null width 10

                textbutton "Actualizar":
                    action Function(rgc_gallery_open, rgc_gallery_filter_kind)

                textbutton "Volver":
                    xalign 1.0
                    action Return()

            hbox:
                spacing 10

                text "Filtros:" size 20

                textbutton rgc_img_label:
                    action Function(rgc_gallery_set_filter, "img")

                textbutton rgc_vid_label:
                    action Function(rgc_gallery_set_filter, "vid")

                textbutton rgc_all_label:
                    action Function(rgc_gallery_set_filter, "all")

            if not rgc_items:
                text "No se encontraron archivos para este filtro."
            else:
                frame:
                    xfill True
                    yfill True
                    padding (10, 10)

                    vbox:
                        spacing 8
                        xalign 0.5

                        for rgc_row in range(rgc_rows):
                            hbox:
                                spacing 10
                                xalign 0.5

                                for rgc_col in range(rgc_cols):
                                    $ rgc_slot = (rgc_row * rgc_cols) + rgc_col
                                    if rgc_slot < len(rgc_page_items):
                                        $ rgc_it = rgc_page_items[rgc_slot]
                                        $ rgc_kind = rgc_it[0]
                                        $ rgc_fn = rgc_it[1]
                                        $ rgc_absolute_index = rgc_start + rgc_slot
                                        $ rgc_preview = rgc_gallery_preview_displayable(rgc_kind, rgc_fn)

                                        button:
                                            xsize rgc_thumb_w
                                            ysize rgc_thumb_h
                                            background Solid("#111")
                                            hover_background Solid("#1b1b1b")
                                            action Function(rgc_gallery_open_viewer, rgc_absolute_index)

                                            fixed:
                                                xfill True
                                                yfill True

                                                add rgc_gallery_scaled(rgc_preview, rgc_thumb_w, rgc_thumb_h) xalign 0.5 yalign 0.5

                                                if rgc_kind == "vid":
                                                    text "▶" size 42 xalign 0.5 yalign 0.5

                                    else:
                                        null width rgc_thumb_w height rgc_thumb_h

                hbox:
                    xalign 0.5
                    spacing 18

                    textbutton "<":
                        sensitive rgc_page > 0
                        action Function(rgc_gallery_page_delta, -1)

                    text rgc_page_label size 20

                    textbutton ">":
                        sensitive rgc_page < (rgc_total_pages - 1)
                        action Function(rgc_gallery_page_delta, 1)


label rgc_gallery_selftest:
    $ rgc_gallery_refresh()
    $ rgc_selftest_images = len(rgc_gallery_image_files)
    $ rgc_selftest_videos = len(rgc_gallery_video_files)
    $ rgc_selftest_total = len(rgc_gallery_all_items)
    "[rgc_selftest_images] imágenes detectadas."
    "[rgc_selftest_videos] videos detectados."
    "[rgc_selftest_total] elementos totales detectados."
    return
