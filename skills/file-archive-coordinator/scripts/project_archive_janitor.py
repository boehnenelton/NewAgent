#!/usr/bin/env python3
# ==============================================================================
# Script Name: project_archive_janitor
# Description: Layer 6 session initialization maintenance janitor sweeping
#              download directories, parsing solid integer package versions,
#              compressing directories, and enforcing archive retention.
# Version: 1.0.0
# Date Created: 2026-10-22
# Author: Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
# RELATIONAL_ID: e4a819dc-72e5-4f01-9b34-8c1d5e2a9f47
# ==============================================================================

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VERSION: str = "1.0.0"
PACKAGE_VERSION: str = "100"
AUTHOR: str = "Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton"
RELATIONAL_ID: str = "e4a819dc-72e5-4f01-9b34-8c1d5e2a9f47"

LOGGER_INSTANCE: logging.Logger = logging.getLogger("ProjectArchiveJanitor")


def get_runtime_script_directory() -> Path:
    """Resolve and return absolute directory of the running script."""
    return Path(__file__).resolve().parent


SCRIPT_PATH: Path = get_runtime_script_directory()


def initialize_logging_subsystem(configured_log_level_name: str = "INFO") -> None:
    """Configure standard logging subsystem avoiding raw print statements."""
    numeric_logging_level: int = getattr(
        logging, configured_log_level_name.upper(), logging.INFO
    )
    logging.basicConfig(
        level=numeric_logging_level,
        format="[%(asctime)s] [%(levelname)s] [ProjectArchiveJanitor] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def resolve_canonical_environment_paths() -> Dict[str, Path]:
    """
    Resolve paths from canonical definitions.json (or fallback paths.json) or apply standard system defaults.
    Never hardcode storage paths in runtime business logic.
    """
    system_paths_map: Dict[str, Path] = {
        "DOWNLOAD_ROOT": Path("/storage/emulated/0/Download"),
        "PROJECTS_ARCHIVE_ROOT": Path("/storage/emulated/0/Admin/Core/Projects_Archive"),
    }

    env_definitions_path: Path = Path("/storage/emulated/0/.env/user/definitions.json")
    user_paths_config_path: Path = Path("/storage/emulated/0/.env/user/paths.json")
    target_config_path = env_definitions_path if env_definitions_path.is_file() else user_paths_config_path

    if target_config_path.is_file():
        try:
            with open(target_config_path, "r", encoding="utf-8") as paths_file_handle:
                parsed_bejson_document: Dict[str, Any] = json.load(paths_file_handle)

            field_definitions_list: List[Dict[str, str]] = parsed_bejson_document.get("Fields", [])
            field_map_cache: Dict[str, int] = {
                field_entry.get("name", ""): field_index
                for field_index, field_entry in enumerate(field_definitions_list)
            }
            var_name_column_index: int = field_map_cache.get("var_name", 0)
            var_value_column_index: int = field_map_cache.get("var_value", 1)

            for record_row in parsed_bejson_document.get("Values", []):
                variable_name_string: str = str(record_row[var_name_column_index])
                variable_value_string: str = str(record_row[var_value_column_index])
                if variable_name_string == "PROJECTS_ARCHIVE_ROOT":
                    system_paths_map["PROJECTS_ARCHIVE_ROOT"] = Path(variable_value_string)
                elif variable_name_string == "INTERNAL_STORAGE":
                    system_paths_map["DOWNLOAD_ROOT"] = Path(variable_value_string) / "Download"
        except Exception as paths_resolution_exception:
            LOGGER_INSTANCE.warning(
                "Unable to parse %s (%s). Using fallback paths.",
                target_config_path.name,
                str(paths_resolution_exception),
            )

    return system_paths_map


@dataclass
class ParsedPackageRecord:
    filesystem_path: Path
    project_canonical_name: str
    project_display_name: str
    raw_version_string: str
    version_numeric_tuple: Tuple[int, ...]
    raw_package_string: str
    package_numeric_tuple: Tuple[int, ...]
    build_numeric_integer: int
    is_directory_flag: bool

    @property
    def sorting_tuple(self) -> Tuple[Tuple[int, ...], Tuple[int, ...], int, float]:
        """Comparable tuple for ordering versions: (version, pkg, build, mtime)."""
        file_mtime_float: float = 0.0
        try:
            file_mtime_float = self.filesystem_path.stat().st_mtime
        except OSError:
            pass
        return (
            self.version_numeric_tuple,
            self.package_numeric_tuple,
            self.build_numeric_integer,
            file_mtime_float,
        )


def parse_version_string_to_tuple(raw_version_token: str) -> Tuple[int, ...]:
    """Convert version string e.g. '1_0_1', '2.0.0', or '2134' into integer tuple for comparison."""
    token_components: List[str] = re.split(r"[_.]", raw_version_token)
    parsed_integers_list: List[int] = []
    for individual_component in token_components:
        cleaned_digits: str = "".join(filter(str.isdigit, individual_component))
        if cleaned_digits:
            parsed_integers_list.append(int(cleaned_digits))
        else:
            parsed_integers_list.append(0)
    return tuple(parsed_integers_list) if parsed_integers_list else (0,)


def evaluate_package_filename_match(
    candidate_filesystem_path: Path,
) -> Optional[ParsedPackageRecord]:
    """
    Regex parsing for Policy §3.1 package format: (PROJECT_NAME)-(VERSION)-(PKGVERSION)
    Accepts dotted versions, hyphens in project names, and trailing build offsets.
    """
    target_entry_name: str = candidate_filesystem_path.name
    package_naming_regex_pattern: str = (
        r"^(?P<project_name>[A-Za-z0-9_.-]+?)"
        r"-V(?P<version>[0-9_.]+)"
        r"-PKG(?P<pkg_version>[0-9_.]+)"
        r"(?:-(?P<build>[0-9_]+))?"
        r"(?P<archive_ext>\.zip)?$"
    )
    regex_matcher: Optional[re.Match] = re.match(
        package_naming_regex_pattern, target_entry_name, re.IGNORECASE
    )
    if not regex_matcher:
        return None

    matched_groups_dictionary = regex_matcher.groupdict()
    project_display_name_string: str = matched_groups_dictionary["project_name"]
    project_canonical_key: str = project_display_name_string.lower()
    raw_version_string: str = matched_groups_dictionary["version"]
    raw_package_string: str = matched_groups_dictionary["pkg_version"]
    raw_build_string: Optional[str] = matched_groups_dictionary.get("build")

    parsed_version_tuple: Tuple[int, ...] = parse_version_string_to_tuple(raw_version_string)
    parsed_package_tuple: Tuple[int, ...] = parse_version_string_to_tuple(raw_package_string)
    parsed_build_number: int = int(raw_build_string) if raw_build_string else 0
    is_loose_directory: bool = candidate_filesystem_path.is_dir()

    return ParsedPackageRecord(
        filesystem_path=candidate_filesystem_path,
        project_canonical_name=project_canonical_key,
        project_display_name=project_display_name_string,
        raw_version_string=raw_version_string,
        version_numeric_tuple=parsed_version_tuple,
        raw_package_string=raw_package_string,
        package_numeric_tuple=parsed_package_tuple,
        build_numeric_integer=parsed_build_number,
        is_directory_flag=is_loose_directory,
    )


def compute_file_sha256_checksum(target_file_path: Path) -> str:
    """Compute SHA-256 fingerprint for duplicate detection."""
    sha256_hash_accumulator = hashlib.sha256()
    try:
        with open(target_file_path, "rb") as file_binary_handle:
            for binary_chunk in iter(lambda: file_binary_handle.read(65536), b""):
                sha256_hash_accumulator.update(binary_chunk)
        return sha256_hash_accumulator.hexdigest()
    except OSError:
        return ""


def compress_directory_to_zip(source_directory_path: Path) -> Path:
    """Compress loose project directory into a standardized ZIP archive."""
    destination_zip_path: Path = source_directory_path.with_suffix(".zip")
    LOGGER_INSTANCE.info(
        "Compressing loose directory %s -> %s",
        source_directory_path.name,
        destination_zip_path.name,
    )
    with zipfile.ZipFile(destination_zip_path, "w", zipfile.ZIP_DEFLATED) as zip_writer_handle:
        for root_directory_path, _, child_filenames_list in os.walk(source_directory_path):
            for individual_child_file in child_filenames_list:
                full_child_file_path = Path(root_directory_path) / individual_child_file
                relative_archive_path = full_child_file_path.relative_to(source_directory_path)
                zip_writer_handle.write(full_child_file_path, arcname=str(relative_archive_path))
    return destination_zip_path


def load_archive_registry_cache(projects_archive_root_directory: Path) -> Dict[str, Tuple[str, str]]:
    """Load canonical project type and status mappings from archive_registry.104a.bejson using Field Map Cache."""
    registry_file_path = projects_archive_root_directory / "archive_registry.104a.bejson"
    type_map: Dict[str, Tuple[str, str]] = {}
    if not registry_file_path.is_file():
        return type_map
    try:
        with open(registry_file_path, "r", encoding="utf-8") as file_handle:
            bejson_doc = json.load(file_handle)
        fields = bejson_doc.get("Fields", [])
        field_map = {f.get("name"): i for i, f in enumerate(fields)}
        name_idx = field_map.get("Project_Name")
        type_idx = field_map.get("Type")
        status_idx = field_map.get("Status")
        if name_idx is not None and type_idx is not None:
            for row in bejson_doc.get("Values", []):
                p_name = str(row[name_idx]).strip().lower()
                p_type = str(row[type_idx]).strip().lower()
                p_status = str(row[status_idx]).strip() if status_idx is not None else "Active"
                if p_name and p_type:
                    type_map[p_name] = (p_type, p_status)
    except Exception as exc:
        LOGGER_INSTANCE.warning("Error loading archive registry: %s", str(exc))
    return type_map


def resolve_project_type_and_status(
    project_display_name: str,
    projects_archive_root_directory: Path,
    registry_cache: Dict[str, Tuple[str, str]],
) -> Tuple[str, str]:
    """Resolve canonical project type and status according to Project Type Ledger and <Status>/<Type> archive hierarchy."""
    canonical_key = project_display_name.lower()
    if canonical_key in registry_cache:
        return registry_cache[canonical_key]

    known_statuses = ("Active", "Inactive", "Legacy", "Archived")
    known_types = ("python", "bash", "library", "react", "skill", "website", "app", "angular", "android_app", "powershell")
    for status_cand in known_statuses:
        for type_cand in known_types:
            if (projects_archive_root_directory / status_cand / type_cand / project_display_name).is_dir():
                return type_cand, status_cand

    default_status = "Active"
    if canonical_key.startswith("lib_") or "librar" in canonical_key or "scaffold" in canonical_key:
        return "library", default_status
    if "skill" in canonical_key or canonical_key.startswith("agy"):
        return "skill", default_status
    if canonical_key.startswith("bash") or canonical_key == "autobase64":
        return "bash", default_status
    if "react" in canonical_key:
        return "react", default_status
    if "engine_js" in canonical_key:
        return "app", default_status
    if "html" in canonical_key:
        return "website", default_status
    return "python", default_status


def execute_session_initialization_sweep(
    download_root_directory: Path,
    projects_archive_root_directory: Path,
    dry_run_simulation_flag: bool = False,
) -> Dict[str, Any]:
    """
    Executes the Initialization Maintenance Sweep per Policy §1.1 & §3.1:
    1. Scan Download directory for project package patterns.
    2. Group packages by project name.
    3. Compress any loose folders to ZIP.
    4. Retain latest version in Download; move older releases to Projects_Archive/<Type>/<ProjectName>/.
    5. Prune duplicate identical releases in Projects_Archive.
    """
    sweep_summary_statistics: Dict[str, int] = {
        "discovered_packages_count": 0,
        "compressed_directories_count": 0,
        "archived_packages_count": 0,
        "pruned_duplicates_count": 0,
        "retained_latest_count": 0,
    }

    if not download_root_directory.is_dir():
        LOGGER_INSTANCE.error(
            "Download directory does not exist: %s", str(download_root_directory)
        )
        return sweep_summary_statistics

    projects_archive_root_directory.mkdir(parents=True, exist_ok=True)
    registry_type_cache = load_archive_registry_cache(projects_archive_root_directory)

    # 1. Discover all matching packages and directories
    discovered_records_map: Dict[str, List[ParsedPackageRecord]] = {}

    for directory_child_entry in download_root_directory.iterdir():
        parsed_record_result: Optional[ParsedPackageRecord] = evaluate_package_filename_match(
            directory_child_entry
        )
        if parsed_record_result is not None:
            project_key = parsed_record_result.project_canonical_name
            if project_key not in discovered_records_map:
                discovered_records_map[project_key] = []
            discovered_records_map[project_key].append(parsed_record_result)
            sweep_summary_statistics["discovered_packages_count"] += 1

    LOGGER_INSTANCE.info(
        "Sweep identified %d project package(s) across %d distinct project(s).",
        sweep_summary_statistics["discovered_packages_count"],
        len(discovered_records_map),
    )

    # 2. Process each project family
    for canonical_project_key, package_records_list in discovered_records_map.items():
        # First compress any loose directories
        normalized_records_list: List[ParsedPackageRecord] = []
        for individual_package_record in package_records_list:
            if individual_package_record.is_directory_flag:
                if not dry_run_simulation_flag:
                    generated_zip_path = compress_directory_to_zip(
                        individual_package_record.filesystem_path
                    )
                    shutil.rmtree(individual_package_record.filesystem_path)
                    sweep_summary_statistics["compressed_directories_count"] += 1
                    reparsed_record = evaluate_package_filename_match(generated_zip_path)
                    if reparsed_record is not None:
                        normalized_records_list.append(reparsed_record)
                else:
                    LOGGER_INSTANCE.info(
                        "[DRY-RUN] Would compress directory %s to ZIP",
                        individual_package_record.filesystem_path.name,
                    )
                    normalized_records_list.append(individual_package_record)
            else:
                normalized_records_list.append(individual_package_record)

        # Deduplicate records by resolved filesystem path
        seen_paths = set()
        deduped_records: List[ParsedPackageRecord] = []
        for rec in normalized_records_list:
            if rec.filesystem_path not in seen_paths:
                seen_paths.add(rec.filesystem_path)
                deduped_records.append(rec)
        normalized_records_list = deduped_records

        if not normalized_records_list:
            continue

        # Skip archiving library development variants per user policy (handled via library maintenance)
        if "libraries" in canonical_project_key:
            LOGGER_INSTANCE.info(
                "Skipping archiving for library variant '%s' per policy.",
                canonical_project_key,
            )
            continue

        # Sort packages ascending so highest version is last
        normalized_records_list.sort(key=lambda record_item: record_item.sorting_tuple)
        latest_package_record: ParsedPackageRecord = normalized_records_list[-1]
        older_package_records_list: List[ParsedPackageRecord] = normalized_records_list[:-1]

        project_display_name = latest_package_record.project_display_name
        project_type, project_status = resolve_project_type_and_status(
            project_display_name,
            projects_archive_root_directory,
            registry_type_cache,
        )
        target_project_archive_dir: Path = (
            projects_archive_root_directory / project_status / project_type / project_display_name
        )

        LOGGER_INSTANCE.info(
            "Project '%s': Retaining latest version in Download [%s]",
            project_display_name,
            latest_package_record.filesystem_path.name,
        )
        sweep_summary_statistics["retained_latest_count"] += 1

        # Move older versions to project archive
        for older_record in older_package_records_list:
            source_file_path = older_record.filesystem_path
            if not source_file_path.exists():
                continue
            destination_file_path = target_project_archive_dir / source_file_path.name

            if dry_run_simulation_flag:
                LOGGER_INSTANCE.info(
                    "[DRY-RUN] Would move %s -> %s",
                    str(source_file_path),
                    str(destination_file_path),
                )
                sweep_summary_statistics["archived_packages_count"] += 1
                continue

            target_project_archive_dir.mkdir(parents=True, exist_ok=True)

            if destination_file_path.exists():
                source_checksum = compute_file_sha256_checksum(source_file_path)
                destination_checksum = compute_file_sha256_checksum(destination_file_path)
                if source_checksum == destination_checksum:
                    LOGGER_INSTANCE.info(
                        "Identical build already archived (%s). Pruning duplicate in Download.",
                        source_file_path.name,
                    )
                    source_file_path.unlink()
                    sweep_summary_statistics["pruned_duplicates_count"] += 1
                    continue
                else:
                    disambiguated_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    destination_file_path = (
                        target_project_archive_dir
                        / f"{source_file_path.stem}_{disambiguated_timestamp}{source_file_path.suffix}"
                    )

            shutil.move(str(source_file_path), str(destination_file_path))
            LOGGER_INSTANCE.info(
                "Archived: %s -> %s",
                source_file_path.name,
                str(destination_file_path),
            )
            sweep_summary_statistics["archived_packages_count"] += 1

    return sweep_summary_statistics


def main() -> int:
    """Command-line entrypoint for Project Archive Janitor."""
    initialize_logging_subsystem("INFO")

    cli_argument_parser = argparse.ArgumentParser(
        description="Layer 6 Project Archive Janitor for Session Initialization Maintenance",
        add_help=True,
    )
    cli_argument_parser.add_argument(
        "--version",
        action="store_true",
        help="Display version, release information, and author metadata.",
    )
    cli_argument_parser.add_argument(
        "--config",
        action="store_true",
        help="Display active environment paths and configuration.",
    )
    cli_argument_parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset temporary janitor audit caches and verify directories.",
    )
    cli_argument_parser.add_argument(
        "--sweep",
        action="store_true",
        help="Execute the full initialization sweep and file consolidation.",
    )
    cli_argument_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the sweep without moving or deleting files.",
    )

    parsed_cli_arguments = cli_argument_parser.parse_args()
    system_paths_map = resolve_canonical_environment_paths()

    if parsed_cli_arguments.version:
        LOGGER_INSTANCE.info(
            "project_archive_janitor v%s (Package %s) | Author: %s | RELATIONAL_ID: %s",
            VERSION,
            PACKAGE_VERSION,
            AUTHOR,
            RELATIONAL_ID,
        )
        return 0

    if parsed_cli_arguments.config:
        LOGGER_INSTANCE.info("Active Project Archive Janitor Configuration:")
        for path_key, resolved_path in system_paths_map.items():
            LOGGER_INSTANCE.info("  %s = %s", path_key, str(resolved_path))
        return 0

    if parsed_cli_arguments.reset:
        LOGGER_INSTANCE.info("Resetting janitor directory verification...")
        system_paths_map["DOWNLOAD_ROOT"].mkdir(parents=True, exist_ok=True)
        system_paths_map["PROJECTS_ARCHIVE_ROOT"].mkdir(parents=True, exist_ok=True)
        LOGGER_INSTANCE.info("Janitor path structures verified successfully.")
        return 0

    # Default to sweep if --sweep or --dry-run or no args
    is_dry_run = parsed_cli_arguments.dry_run
    LOGGER_INSTANCE.info(
        "Commencing Initialization Maintenance Sweep (Dry Run: %s)...",
        str(is_dry_run),
    )
    sweep_results = execute_session_initialization_sweep(
        download_root_directory=system_paths_map["DOWNLOAD_ROOT"],
        projects_archive_root_directory=system_paths_map["PROJECTS_ARCHIVE_ROOT"],
        dry_run_simulation_flag=is_dry_run,
    )
    LOGGER_INSTANCE.info(
        "Sweep Complete: %d discovered, %d compressed, %d archived, %d duplicates pruned, %d latest retained.",
        sweep_results["discovered_packages_count"],
        sweep_results["compressed_directories_count"],
        sweep_results["archived_packages_count"],
        sweep_results["pruned_duplicates_count"],
        sweep_results["retained_latest_count"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
