"""안드로이드 테더링 유동 IP 변경 (ADB 모바일 데이터 토글).

전제: PC가 해당 안드로이드 폰의 테더링(USB 권장)으로 인터넷을 사용하고,
ADB(USB 디버깅)로 폰을 제어할 수 있어야 한다.

흐름: 현재 공인 IP 확인 → svc data disable → 대기 → svc data enable →
재연결 후 공인 IP가 바뀔 때까지 폴링.
"""
from __future__ import annotations

import subprocess
import time
from typing import Callable

import requests

LogFn = Callable[[str], None]

_IP_SERVICES = [
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
]


def get_public_ip(timeout: int = 8) -> str | None:
    """현재 공인 IP를 반환한다. 실패 시 None."""
    for url in _IP_SERVICES:
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.ok:
                ip = resp.text.strip()
                if ip:
                    return ip
        except Exception:
            continue
    return None


def _run_adb(adb_cmd: str, args: list[str], timeout: int = 20) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [adb_cmd, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (proc.stdout + proc.stderr).strip()
        return proc.returncode == 0, out
    except FileNotFoundError:
        return False, f"ADB 실행 파일을 찾을 수 없습니다: {adb_cmd}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def adb_available(adb_cmd: str) -> tuple[bool, str]:
    """ADB 설치 및 기기 연결 여부를 확인한다."""
    ok, out = _run_adb(adb_cmd, ["devices"])
    if not ok:
        return False, out or "ADB 실행 실패"
    # 'device' 상태의 기기가 한 대라도 있는지 확인
    lines = [l for l in out.splitlines()[1:] if l.strip()]
    devices = [l for l in lines if l.endswith("\tdevice")]
    if not devices:
        return False, "연결된 ADB 기기가 없습니다 (USB 디버깅 허용 확인)."
    return True, f"기기 {len(devices)}대 연결됨"


def set_mobile_data(adb_cmd: str, enable: bool) -> tuple[bool, str]:
    """ADB로 모바일 데이터를 켜거나 끈다 (svc data)."""
    return _run_adb(adb_cmd, ["shell", "svc", "data", "enable" if enable else "disable"])


def rotate_ip(
    adb_cmd: str,
    *,
    off_wait: float = 4.0,
    on_wait: float = 5.0,
    verify_timeout: float = 40.0,
    poll_interval: float = 3.0,
    log: LogFn = print,
) -> bool:
    """모바일 데이터를 껐다 켜서 유동 IP를 변경한다.

    반환: 공인 IP가 실제로 바뀌면 True. (변경 확인 실패 시 False)
    """
    available, msg = adb_available(adb_cmd)
    if not available:
        log(f"IP 변경 불가: {msg}")
        return False

    old_ip = get_public_ip()
    log(f"현재 IP: {old_ip or '확인 실패'}")

    ok, out = set_mobile_data(adb_cmd, False)
    if not ok:
        log(f"데이터 끄기 실패: {out}")
        return False
    log("모바일 데이터 OFF")
    time.sleep(off_wait)

    ok, out = set_mobile_data(adb_cmd, True)
    if not ok:
        log(f"데이터 켜기 실패: {out}")
        return False
    log("모바일 데이터 ON, 재연결 대기...")
    time.sleep(on_wait)

    deadline = time.time() + verify_timeout
    while time.time() < deadline:
        new_ip = get_public_ip()
        if new_ip and new_ip != old_ip:
            log(f"IP 변경 성공: {old_ip} -> {new_ip}")
            return True
        time.sleep(poll_interval)

    final_ip = get_public_ip()
    if final_ip and final_ip != old_ip:
        log(f"IP 변경 성공: {old_ip} -> {final_ip}")
        return True
    log(f"IP가 변경되지 않았습니다 (현재: {final_ip}). CGNAT이거나 테더링 경로가 아닐 수 있습니다.")
    return False
