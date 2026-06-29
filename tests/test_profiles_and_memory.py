from premode.profiles import PROFILES, choose_auto_profile


def test_resource_profile_caps():
    assert PROFILES["lite"].max_file_bytes == 65536
    assert PROFILES["standard"].max_total_selected_context_bytes == 2000000
    assert PROFILES["pro"].max_index_files == 100000


def test_auto_profile_fallbacks():
    assert choose_auto_profile(None) in {"standard", "lite", "pro"}
    assert choose_auto_profile(8 * 1024) == "lite"
    assert choose_auto_profile(16 * 1024) == "standard"
    assert choose_auto_profile(64 * 1024) == "pro"
