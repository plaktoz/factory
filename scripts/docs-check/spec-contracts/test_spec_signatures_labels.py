"""The reader keeps every file a block's label lists, so the contract test can find the one that defines a signature."""

from spec_signatures import block_signatures


def test_a_label_that_lists_two_files_keeps_both_files_in_order():
    # module 9 writes `# adapters/worker/claude.py, fake.py`; a bare second name is in the first name's folder
    block = "# adapters/worker/claude.py, fake.py\nclass FakeWorkerAdapter:\n    def __init__(self, script: dict) -> None\n"
    (sig,) = block_signatures(block, "test")
    assert sig.key == "FakeWorkerAdapter.__init__"
    assert sig.files == ("adapters/worker/claude.py", "adapters/worker/fake.py")
    assert sig.file == "adapters/worker/claude.py"


def test_a_label_that_lists_three_files_in_the_engine_folder_keeps_all_three():
    block = "# loadcfg.py, validate.py, redact.py\ndef mask(text: str) -> str\n"
    (sig,) = block_signatures(block, "test")
    assert sig.files == ("loadcfg.py", "validate.py", "redact.py")


def test_a_single_file_label_gives_one_file():
    block = "# loadcfg.py\ndef load_config(repo: Path | None) -> Config\n"
    (sig,) = block_signatures(block, "test")
    assert sig.files == ("loadcfg.py",)


def test_a_block_with_no_label_gives_no_files():
    (sig,) = block_signatures("def mask(text: str) -> str\n", "test")
    assert sig.files == ()
    assert sig.file is None
