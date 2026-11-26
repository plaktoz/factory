"""The bugfix-target folder is a fixture the tests copy, not tests of this engine: its own pytest files are not collected."""

collect_ignore_glob = ["bugfix-target/*"]
