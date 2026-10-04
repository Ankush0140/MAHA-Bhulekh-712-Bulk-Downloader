import ctypes

def _is_interactive_winsta() -> bool:
    try:
        hwinsta = ctypes.windll.user32.GetProcessWindowStation()
        if not hwinsta:
            return False
        length = ctypes.c_ulong(0)
        ctypes.windll.user32.GetUserObjectInformationW(hwinsta, 2, None, 0, ctypes.byref(length))
        if length.value == 0:
            return False
        buf = ctypes.create_unicode_buffer(length.value // 2)
        ctypes.windll.user32.GetUserObjectInformationW(hwinsta, 2, buf, length.value, ctypes.byref(length))
        return buf.value.lower() == 'winsta0'
    except Exception:
        return False

def get_visible_window_titles() -> list[str]:
    EnumWindows = ctypes.windll.user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
    IsWindowVisible = ctypes.windll.user32.IsWindowVisible
    GetWindowText = ctypes.windll.user32.GetWindowTextW
    GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW

    titles = []

    def foreach_window(hwnd, lParam):
        if IsWindowVisible(hwnd):
            length = GetWindowTextLength(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            GetWindowText(hwnd, buff, length + 1)
            title = buff.value
            if title:
                titles.append(title)
        return True

    try:
        EnumWindows(EnumWindowsProc(foreach_window), 0)
    except Exception:
        pass
        
    return titles

def has_visible_window_with_title(target_title: str) -> bool:
    if not _is_interactive_winsta():
        return False

    for title in get_visible_window_titles():
        if target_title in title:
            return True
            
    return False
