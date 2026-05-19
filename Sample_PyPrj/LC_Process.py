import os
import re
from pathlib import Path

from dotenv import load_dotenv

from project_paths import resolve_project_relative


class FileCleansing:
    """Utility class for cleansing file and folder names of invalid characters."""

    # Invalid characters for filenames (Windows + common reserved chars)
    _INVALID_CHARS = r'[<>:"/\\|?*\x00-\x1f]'
    _invalid_chars_regex = re.compile(_INVALID_CHARS)

    @staticmethod
    def remove_invalid_chars(file_name: str) -> str:
        """Replace invalid filename characters with underscores."""
        return FileCleansing._invalid_chars_regex.sub("_", file_name)


def build_folder_path(
    root_folder_path: str, organization_name: str, organization_id: str, user_name: str
) -> str:
    """
    Build a folder path combining root path, cleansed organization info, and cleansed username.

    Equivalent to C#:
        var folderPath = Path.Combine(RootFolderPath, cleansedOrganizationName + "_" + organization.Id, cleansedUserName);
    """
    cleansed_organization_name = FileCleansing.remove_invalid_chars(organization_name)
    cleansed_user_name = FileCleansing.remove_invalid_chars(user_name)

    folder_path = os.path.join(
        root_folder_path,
        f"{cleansed_organization_name}_{organization_id}",
        cleansed_user_name,
    )
    return folder_path


# Example usage
if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    raw_root = (os.getenv("LC_BATCH_ROOT_FOLDER") or "").strip()
    RootFolderPath = resolve_project_relative(raw_root) if raw_root else ""
    if not RootFolderPath:
        raise SystemExit(
            "Set LC_BATCH_ROOT_FOLDER in .env (see .env.example), e.g. UNC path to batch files."
        )
    organization_name = "APS Bank Ltd"
    organization_id = "4650544241"
    user_name = "andrew.attard"

    # Get Folder Path
    folder_path = build_folder_path(
        root_folder_path=RootFolderPath,
        organization_name=organization_name,
        organization_id=organization_id,
        user_name=user_name,
    )
    print(f"Folder Path: {folder_path}")
