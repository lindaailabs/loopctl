"""Configuration loading and machine-local path resolution."""

from loopctl.config.loader import load_project
from loopctl.config.paths import data_dir, projects_root

__all__ = ["load_project", "data_dir", "projects_root"]
