#!/usr/bin/env python3
"""Chụp ảnh màn hình trình duyệt ACC001 qua BrowserClient."""

import sys
from pathlib import Path

# Add camo-manager to path
sys.path.insert(0, str(Path(__file__).parent))

from browser_client import BrowserClient, get_socket_path, is_running, status_all

def main():
    profile_name = "ACC001"
    
    print("=" * 60)
    print(f"SỐT ẢNH MÀN HÌNH TRÌNH DUYỆT: {profile_name}")
    print("=" * 60)
    
    # Kiểm tra status các profile đang chạy
    print("\n📊 Status hiện tại:")
    for s in status_all():
        print(s)
    
    # Kết nối tới browser (auto-start nếu chưa chạy)
    print(f"\n🔌 Kết nối tới {profile_name}...")
    try:
        with BrowserClient(profile_name, auto_start=True, headless=False) as bc:
            url = bc.get_url()
            print(f"   URL hiện tại: {url}")
            
            # Chụp ảnh màn hình
            ss_dir = Path(__file__).parent.parent / "camoufox-profile" / profile_name / "screenshots"
            ss_dir.mkdir(parents=True, exist_ok=True)
            ss_path = ss_dir / f"screenshot_2026-03-09_1157.png"
            
            print(f"\n📸 Chụp ảnh tại: {ss_path}")
            bc.screenshot(str(ss_path), full_page=False)
            
            # Đọc và hiển thị thông tin file
            if ss_path.exists():
                size = ss_path.stat().st_size
                print(f"   ✅ File chụp được - Kích thước: {size:,} bytes ({size/1024:.1f} KB)")
                
    except Exception as e:
        print(f"\n❌ Lỗi khi chụp ảnh: {e}")
        return 1
    
    print("\n✅ HOÀN THÀNH!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
