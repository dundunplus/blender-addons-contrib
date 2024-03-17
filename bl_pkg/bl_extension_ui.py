# SPDX-FileCopyrightText: 2023 Blender Foundation
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
GUI (WARNING) this is a hack!
Written to allow a UI without modifying Blender.
"""

__all__ = (
    "display_errors",
    "extension_drop_file_popover",
    "extension_drop_file_popover_close_as_needed",
    "extension_drop_url_popover",
    "extension_drop_url_popover_close_as_needed",
    "register",
    "unregister",
)

import bpy

from bpy.types import (
    Menu,
    Panel,
)

from bl_ui.space_userpref import (
    USERPREF_PT_addons,
)

from . import repo_status_text


# -----------------------------------------------------------------------------
# Generic Utilities


def size_as_fmt_string(num: float, *, precision: int = 1) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB"):
        if abs(num) < 1024.0:
            return "{:3.{:d}f}{:s}".format(num, precision, unit)
        num /= 1024.0
    unit = "yb"
    return "{:.{:d}f}{:s}".format(num, precision, unit)


def sizes_as_percentage_string(size_partial: int, size_final: int) -> str:
    if size_final == 0:
        percent = 0.0
    else:
        size_partial = min(size_partial, size_final)
        percent = size_partial / size_final

    return "{:-6.2f}%".format(percent * 100)


def license_info_to_text(license_list):
    # See: https://spdx.org/licenses/
    # - Note that we could include all, for now only common, GPL compatible licenses.
    # - Note that many of the human descriptions are not especially more humanly readable
    #   than the short versions, so it's questionable if we should attempt to add all of these.
    _spdx_id_to_text = {
        "GPL-2.0-only": "GNU General Public License v2.0 only",
        "GPL-2.0-or-later": "GNU General Public License v2.0 or later",
        "GPL-3.0-only": "GNU General Public License v3.0 only",
        "GPL-3.0-or-later": "GNU General Public License v3.0 or later",
    }
    result = []
    for item in license_list:
        if item.startswith("SPDX:"):
            item = item[5:]
            item = _spdx_id_to_text.get(item, item)
        result.append(item)
    return ", ".join(result)


def extension_url_find_repo_index_and_pkg_id(url):
    from .bl_extension_utils import (
        pkg_manifest_archive_url_abs_from_repo_url,
    )
    from .bl_extension_ops import (
        extension_repos_read,
    )
    # return repo_index, pkg_id
    from . import repo_cache_store

    # NOTE: we might want to use `urllib.parse.urlsplit` so it's possible to include variables in the URL.
    url_basename = url.rpartition("/")[2]

    repos_all = extension_repos_read()

    for repo_index, (
            pkg_manifest_remote,
            pkg_manifest_local,
    ) in enumerate(zip(
        repo_cache_store.pkg_manifest_from_remote_ensure(error_fn=print),
        repo_cache_store.pkg_manifest_from_local_ensure(error_fn=print),
    )):
        repo = repos_all[repo_index]
        repo_url = repo.repo_url
        if not repo_url:
            continue
        for pkg_id, item_remote in pkg_manifest_remote.items():
            archive_url = item_remote["archive_url"]
            archive_url_basename = archive_url.rpartition("/")[2]
            # First compare the filenames, if this matches, check the full URL.
            if url_basename != archive_url_basename:
                continue

            # Calculate the absolute URL.
            archive_url_abs = pkg_manifest_archive_url_abs_from_repo_url(repo_url, archive_url)
            if archive_url_abs == url:
                return repo_index, repo.name, pkg_id, item_remote, pkg_manifest_local.get(pkg_id)

    return -1, "", "", None, None


def wm_error(title, body, *, icon):
    def fn(panel, context):
        layout = panel.layout
        layout.label(text=title, icon=icon)
        if body:
            layout.separator(type='LINE')
            layout.label(text=body)

    wm = bpy.context.window_manager
    wm.popover(fn, ui_units_x=14)


def extension_drop_url_popover(url):
    repo_index, repo_name, pkg_id, item_remote, item_local = extension_url_find_repo_index_and_pkg_id(url)

    if repo_index == -1:
        wm_error("Extension: URL not found in remote repositories!", url, icon='ERROR')
        return

    if item_local is not None:
        wm_error("Extension: {:s}".format(pkg_id), "Already installed!", icon='ERROR')
        return

    USERPREF_PT_extensions_bl_pkg_drop_url.drop_variables = repo_index, repo_name, pkg_id, item_remote
    bpy.ops.wm.call_panel(name="USERPREF_PT_extensions_bl_pkg_drop_url", keep_open=True)


def extension_drop_url_popover_close_as_needed():
    if USERPREF_PT_extensions_bl_pkg_drop_url.drop_variables is None:
        return
    USERPREF_PT_extensions_bl_pkg_drop_url.drop_variables = None
    from .bl_extension_ops import wm_close_popup_hack
    wm_close_popup_hack()


def extension_drop_file_popover(url):
    from .bl_extension_ops import repo_iter_valid_local_only
    from .bl_extension_utils import pkg_manifest_dict_from_file_or_error

    if not list(repo_iter_valid_local_only(bpy.context)):
        wm_error("Error", "No Local Repositories", icon='ERROR')
        return

    if isinstance(err := pkg_manifest_dict_from_file_or_error(url), str):
        wm_error("Error", err, icon='ERROR')
        return
    del err

    USERPREF_PT_extensions_bl_pkg_drop_file.drop_variables = url
    bpy.ops.wm.call_panel(name="USERPREF_PT_extensions_bl_pkg_drop_file", keep_open=True)


def extension_drop_file_popover_close_as_needed():
    if USERPREF_PT_extensions_bl_pkg_drop_file.drop_variables is None:
        return
    USERPREF_PT_extensions_bl_pkg_drop_file.drop_variables = None
    from .bl_extension_ops import wm_close_popup_hack
    wm_close_popup_hack()


# -----------------------------------------------------------------------------
# Extensions UI (Legacy)

def extensions_panel_draw_legacy_addons(
        layout,
        context,
        *,
        search_lower,
        enabled_only,
        installed_only,
        used_addon_module_name_map,
):
    # NOTE: this duplicates logic from `USERPREF_PT_addons` eventually this logic should be used instead.
    # Don't de-duplicate the logic as this is a temporary state - as long as extensions remains experimental.
    import addon_utils
    from bpy.app.translations import (
        pgettext_iface as iface_,
    )
    from .bl_extension_ops import (
        pkg_info_check_exclude_filter_ex,
    )

    addons = [
        (mod, addon_utils.module_bl_info(mod))
        for mod in addon_utils.modules(refresh=False)
    ]

    # Initialized on demand.
    user_addon_paths = []

    for mod, bl_info in addons:
        module_name = mod.__name__
        is_extension = addon_utils.check_extension(module_name)
        if is_extension:
            continue

        if search_lower and (
                not pkg_info_check_exclude_filter_ex(
                    bl_info["name"],
                    bl_info["description"],
                    search_lower,
                )
        ):
            continue

        is_enabled = module_name in used_addon_module_name_map
        if enabled_only and (not is_enabled):
            continue

        col_box = layout.column()
        box = col_box.box()
        colsub = box.column()
        row = colsub.row(align=True)

        row.operator(
            "preferences.addon_expand",
            icon='DISCLOSURE_TRI_DOWN' if bl_info["show_expanded"] else 'DISCLOSURE_TRI_RIGHT',
            emboss=False,
        ).module = module_name

        row.operator(
            "preferences.addon_disable" if is_enabled else "preferences.addon_enable",
            icon='CHECKBOX_HLT' if is_enabled else 'CHECKBOX_DEHLT', text="",
            emboss=False,
        ).module = module_name

        sub = row.row()
        sub.active = is_enabled
        sub.label(text="Legacy: " + bl_info["name"])

        if bl_info["warning"]:
            sub.label(icon='ERROR')

        row_right = row.row()
        row_right.alignment = 'RIGHT'

        row_right.label(text="Installed   ")
        row_right.active = False

        if bl_info["show_expanded"]:
            split = box.split(factor=0.15)
            col_a = split.column()
            col_b = split.column()
            if value := bl_info["description"]:
                col_a.label(text="Description:")
                col_b.label(text=iface_(value))

            col_a.label(text="File:")
            col_b.label(text=mod.__file__, translate=False)

            if value := bl_info["author"]:
                col_a.label(text="Author:")
                col_b.label(text=value.split("<", 1)[0].rstrip(), translate=False)
            if value := bl_info["version"]:
                col_a.label(text="Version:")
                col_b.label(text=".".join(str(x) for x in value), translate=False)
            if value := bl_info["warning"]:
                col_a.label(text="Warning:")
                col_b.label(text="  " + iface_(value), icon='ERROR')
            del value

            # Include for consistency.
            col_a.label(text="Type:")
            col_b.label(text="add-on")

            user_addon = USERPREF_PT_addons.is_user_addon(mod, user_addon_paths)

            if bl_info["doc_url"] or bl_info.get("tracker_url"):
                split = box.row().split(factor=0.15)
                split.label(text="Internet:")
                sub = split.row()
                if bl_info["doc_url"]:
                    sub.operator(
                        "wm.url_open", text="Documentation", icon='HELP',
                    ).url = bl_info["doc_url"]
                # Only add "Report a Bug" button if tracker_url is set
                # or the add-on is bundled (use official tracker then).
                if bl_info.get("tracker_url"):
                    sub.operator(
                        "wm.url_open", text="Report a Bug", icon='URL',
                    ).url = bl_info["tracker_url"]
                elif not user_addon:
                    addon_info = (
                        "Name: %s %s\n"
                        "Author: %s\n"
                    ) % (bl_info["name"], str(bl_info["version"]), bl_info["author"])
                    props = sub.operator(
                        "wm.url_open_preset", text="Report a Bug", icon='URL',
                    )
                    props.type = 'BUG_ADDON'
                    props.id = addon_info

            if user_addon:
                rowsub = col_b.row()
                rowsub.alignment = 'RIGHT'
                rowsub.operator(
                    "preferences.addon_remove", text="Uninstall", icon='CANCEL',
                ).module = module_name

            if is_enabled:
                if (addon_preferences := used_addon_module_name_map[module_name].preferences) is not None:
                    USERPREF_PT_addons.draw_addon_preferences(layout, context, addon_preferences)


# -----------------------------------------------------------------------------
# Extensions UI

class display_errors:
    """
    This singleton class is used to store errors which are generated while drawing,
    note that these errors are reasonably obscure, examples are:
    - Failure to parse the repository JSON file.
    - Failure to access the file-system for reading where the repository is stored.

    The current and previous state are compared, when they match no drawing is done,
    this allows the current display errors to be dismissed.
    """
    errors_prev = []
    errors_curr = []

    @staticmethod
    def clear():
        display_errors.errors_prev = display_errors.errors_curr

    @staticmethod
    def draw(layout):
        if display_errors.errors_curr == display_errors.errors_prev:
            return
        box_header = layout.box()
        # Don't clip longer names.
        row = box_header.split(factor=0.9)
        row.label(text="Repository Access Errors:", icon='ERROR')
        rowsub = row.row(align=True)
        rowsub.alignment = 'RIGHT'
        rowsub.operator("bl_pkg.pkg_display_errors_clear", text="", icon='X', emboss=False)

        box_contents = box_header.box()
        for err in display_errors.errors_curr:
            box_contents.label(text=err)


def extensions_panel_draw_impl(
        self,
        context,
        search_lower,
        filter_by_type,
        enabled_only,
        installed_only,
        show_legacy_addons,
        show_development,
):
    """
    Show all the items... we may want to paginate at some point.
    """
    import os
    from .bl_extension_ops import (
        blender_extension_mark,
        blender_extension_show,
        extension_repos_read,
        pkg_info_check_exclude_filter,
        repo_cache_store_refresh_from_prefs,
    )

    from . import repo_cache_store

    # This isn't elegant, but the preferences aren't available on registration.
    if not repo_cache_store.is_init():
        repo_cache_store_refresh_from_prefs()

    layout = self.layout

    # Define a top-most column to place warnings (if-any).
    # Needed so the warnings aren't mixed in with other content.
    layout_topmost = layout.column()

    repos_all = extension_repos_read()

    # To access enabled add-ons.
    show_addons = filter_by_type in {"", "add-on"}
    if show_addons:
        used_addon_module_name_map = {addon.module: addon for addon in context.preferences.addons}

    # Collect exceptions accessing repositories, and optionally show them.
    errors_on_draw = []

    remote_ex = None
    local_ex = None

    def error_fn_remote(ex):
        nonlocal remote_ex
        remote_ex = ex

    def error_fn_local(ex):
        nonlocal remote_ex
        remote_ex = ex

    for repo_index, (
            pkg_manifest_remote,
            pkg_manifest_local,
    ) in enumerate(zip(
        repo_cache_store.pkg_manifest_from_remote_ensure(error_fn=error_fn_remote),
        repo_cache_store.pkg_manifest_from_local_ensure(error_fn=error_fn_local),
    )):
        # Show any exceptions created while accessing the JSON,
        # if the JSON has an IO error while being read or if the directory doesn't exist.
        # In general users should _not_ see these kinds of errors however we cannot prevent
        # IO errors in general and it is better to show a warning than to ignore the error entirely
        # or cause a trace-back which breaks the UI.
        if (remote_ex is not None) or (local_ex is not None):
            repo = repos_all[repo_index]
            # NOTE: `FileNotFoundError` occurs when a repository has been added but has not update with its remote.
            # We may want a way for users to know a repository is missing from the view and they need to run update
            # to access its extensions.
            if remote_ex is not None:
                if isinstance(remote_ex, FileNotFoundError) and (remote_ex.filename == repo.directory):
                    pass
                else:
                    errors_on_draw.append("Remote of \"{:s}\": {:s}".format(repo.name, str(remote_ex)))
                remote_ex = None

            if local_ex is not None:
                if isinstance(local_ex, FileNotFoundError) and (local_ex.filename == repo.directory):
                    pass
                else:
                    errors_on_draw.append("Local of \"{:s}\": {:s}".format(repo.name, str(local_ex)))
                local_ex = None
            continue

        if pkg_manifest_remote is None:
            repo = repos_all[repo_index]
            has_remote = (repo.repo_url != "")
            if has_remote:
                # NOTE: it would be nice to detect when the repository ran sync and it failed.
                # This isn't such an important distinction though, the main thing users should be aware of
                # is that a "sync" is required.
                errors_on_draw.append("Repository: \"{:s}\" must sync with the remote repository.".format(repo.name))
            del repo
            continue
        else:
            repo = repos_all[repo_index]
            has_remote = (repo.repo_url != "")
            del repo

        for pkg_id, item_remote in pkg_manifest_remote.items():
            if filter_by_type and (filter_by_type != item_remote["type"]):
                continue
            if search_lower and (not pkg_info_check_exclude_filter(item_remote, search_lower)):
                continue

            item_local = pkg_manifest_local.get(pkg_id)
            is_installed = item_local is not None

            if installed_only and (is_installed == 0):
                continue

            is_addon = (item_remote["type"] == "add-on")

            if is_addon:
                if is_installed:
                    # Currently we only need to know the module name once installed.
                    addon_module_name = "bl_ext.{:s}.{:s}".format(repos_all[repo_index].module, pkg_id)
                    is_enabled = addon_module_name in used_addon_module_name_map

                else:
                    is_enabled = False
                    addon_module_name = None
            else:
                # TODO: ability to disable.
                is_enabled = is_installed
                addon_module_name = None

            if enabled_only and (not is_enabled):
                continue

            item_version = item_remote["version"]
            if item_local is None:
                item_local_version = None
                is_outdated = False
            else:
                item_local_version = item_local["version"]
                is_outdated = item_local_version != item_version

            key = (pkg_id, repo_index)
            if show_development:
                mark = key in blender_extension_mark
            show = key in blender_extension_show
            del key

            box = layout.box()

            # Left align so the operator text isn't centered.
            colsub = box.column()
            row = colsub.row(align=True)
            # row.label
            if show:
                props = row.operator("bl_pkg.pkg_show_clear", text="", icon='DISCLOSURE_TRI_DOWN', emboss=False)
            else:
                props = row.operator("bl_pkg.pkg_show_set", text="", icon='DISCLOSURE_TRI_RIGHT', emboss=False)
            props.pkg_id = pkg_id
            props.repo_index = repo_index
            del props

            if is_installed:
                if is_addon:
                    row.operator(
                        "preferences.addon_disable" if is_enabled else "preferences.addon_enable",
                        icon='CHECKBOX_HLT' if is_enabled else 'CHECKBOX_DEHLT',
                        text="",
                        emboss=False,
                    ).module = addon_module_name
                else:
                    # Use a place-holder checkbox icon to avoid odd text alignment when mixing with installed add-ons.
                    # Non add-ons have no concept of "enabled" right now, use installed.
                    row.operator(
                        "bl_pkg.extension_disable",
                        text="",
                        icon='CHECKBOX_HLT',
                        emboss=False,
                    )
            else:
                # Not installed, always placeholder.
                row.operator("bl_pkg.extensions_enable_not_installed", text="", icon='CHECKBOX_DEHLT', emboss=False)

            if show_development:
                if mark:
                    props = row.operator("bl_pkg.pkg_mark_clear", text="", icon='RADIOBUT_ON', emboss=False)
                else:
                    props = row.operator("bl_pkg.pkg_mark_set", text="", icon='RADIOBUT_OFF', emboss=False)
                props.pkg_id = pkg_id
                props.repo_index = repo_index
                del props

            sub = row.row()
            sub.active = is_enabled
            sub.label(text=item_remote["name"])
            del sub

            row_right = row.row()
            row_right.alignment = 'RIGHT'

            if has_remote:
                if is_installed:
                    # Include uninstall below.
                    if is_outdated:
                        props = row_right.operator("bl_pkg.pkg_install", text="Update")
                        props.repo_index = repo_index
                        props.pkg_id = pkg_id
                        del props
                    else:
                        # Right space for alignment with the button.
                        row_right.label(text="Installed   ")
                        row_right.active = False
                else:
                    props = row_right.operator("bl_pkg.pkg_install", text="Install")
                    props.repo_index = repo_index
                    props.pkg_id = pkg_id
                    del props
            else:
                # Right space for alignment with the button.
                row_right.label(text="Installed   ")
                row_right.active = False

            if show:
                split = box.split(factor=0.15)
                col_a = split.column()
                col_b = split.column()

                col_a.label(text="Description:")
                # The full description may be multiple lines (not yet supported by Blender's UI).
                col_b.label(text=item_remote["tagline"])

                if is_installed:
                    col_a.label(text="Path:")
                    col_b.label(text=os.path.join(repos_all[repo_index].directory, pkg_id), translate=False)

                # Remove the maintainers email while it's not private, showing prominently
                # could cause maintainers to get direct emails instead of issue tracking systems.
                col_a.label(text="Maintainer:")
                col_b.label(text=item_remote["maintainer"].split("<", 1)[0].rstrip(), translate=False)

                col_a.label(text="License:")
                col_b.label(text=license_info_to_text(item_remote["license"]))

                col_a.label(text="Version:")
                if is_outdated:
                    col_b.label(text="{:s} ({:s} available)".format(item_local_version, item_version))
                else:
                    col_b.label(text=item_version)

                if has_remote:
                    col_a.label(text="Size:")
                    col_b.label(text=size_as_fmt_string(item_remote["archive_size"]))

                if not filter_by_type:
                    col_a.label(text="Type:")
                    col_b.label(text=item_remote["type"])

                if len(repos_all) > 1:
                    col_a.label(text="Repository:")
                    col_b.label(text=repos_all[repo_index].name)

                if value := item_remote.get("website"):
                    col_a.label(text="Internet:")
                    # Use half size button, for legacy add-ons there are two, here there is one
                    # however one large button looks silly, so use a half size still.
                    col_b.split(factor=0.5).operator("wm.url_open", text="Website", icon='HELP').url = value
                del value

                # Note that we could allow removing extensions from non-remote extension repos
                # although this is destructive, so don't enable this right now.
                if is_installed:
                    rowsub = col_b.row()
                    rowsub.alignment = 'RIGHT'
                    props = rowsub.operator("bl_pkg.pkg_uninstall", text="Uninstall")
                    props.repo_index = repo_index
                    props.pkg_id = pkg_id
                    del props, rowsub

                # Show addon user preferences.
                if is_enabled and is_addon:
                    if (addon_preferences := used_addon_module_name_map[addon_module_name].preferences) is not None:
                        USERPREF_PT_addons.draw_addon_preferences(layout, context, addon_preferences)

    if show_addons and show_legacy_addons:
        extensions_panel_draw_legacy_addons(
            layout,
            context,
            search_lower=search_lower,
            enabled_only=enabled_only,
            installed_only=installed_only,
            used_addon_module_name_map=used_addon_module_name_map,
        )

    # Finally show any errors in a single panel which can be dismissed.
    display_errors.errors_curr = errors_on_draw
    if errors_on_draw:
        display_errors.draw(layout_topmost)


class USERPREF_PT_extensions_bl_pkg_filter(Panel):
    bl_label = "Extensions Filter"

    bl_space_type = 'TOPBAR'  # dummy.
    bl_region_type = 'HEADER'
    bl_ui_units_x = 13

    def draw(self, context):
        layout = self.layout

        wm = context.window_manager
        col = layout.column(heading="Show")
        col.use_property_split = True
        col.prop(wm, "extension_installed_only", text="Installed Extensions")
        sub = col.column()
        sub.active = wm.extension_installed_only
        sub.prop(wm, "extension_enabled_only", text="Enabled Extensions")
        col.prop(wm, "extension_show_legacy_addons", text="Legacy Add-ons")


class USERPREF_MT_extensions_bl_pkg_settings(Menu):
    bl_label = "Extension Settings"

    def draw(self, context):
        layout = self.layout

        addon_prefs = context.preferences.addons[__package__].preferences

        layout.operator("bl_pkg.repo_sync_all", text="Check for Updates", icon='FILE_REFRESH')
        layout.operator("bl_pkg.pkg_upgrade_all", text="Update All", icon='IMPORT')

        layout.separator()

        layout.operator("bl_pkg.pkg_install_files", icon='IMPORT', text="Install from Disk")
        layout.operator("preferences.addon_install", text="Install Legacy Add-on")

        if context.preferences.experimental.use_extension_utils:
            layout.separator()

            layout.prop(addon_prefs, "show_development_reports")

            layout.separator()

            # We might want to expose this for all users, the purpose of this
            # is to refresh after changes have been made to the repos outside of Blender
            # it's disputable if this is a common case.
            layout.operator("preferences.addon_refresh", text="Refresh (file-system)", icon='FILE_REFRESH')
            layout.separator()

            layout.operator("bl_pkg.pkg_install_marked", text="Install Marked", icon='IMPORT')
            layout.operator("bl_pkg.pkg_uninstall_marked", text="Uninstall Marked", icon='X')
            layout.operator("bl_pkg.obsolete_marked")

            layout.separator()

            layout.operator("bl_pkg.repo_lock")
            layout.operator("bl_pkg.repo_unlock")


def extensions_panel_draw(panel, context):
    prefs = context.preferences
    if not prefs.experimental.use_extension_repos:
        # Unexpected, the extension is disabled but this add-on is.
        # In this case don't show the UI as it is confusing.
        return

    from .bl_extension_ops import (
        blender_filter_by_type_map,
    )

    addon_prefs = prefs.addons[__package__].preferences

    show_development = context.preferences.experimental.use_extension_utils
    show_development_reports = show_development and addon_prefs.show_development_reports

    wm = context.window_manager
    layout = panel.layout

    row = layout.split(factor=0.5)
    row_a = row.row()
    row_a.prop(wm, "extension_search", text="", icon='VIEWZOOM')
    row_b = row.row(align=True)
    row_b.prop(wm, "extension_type", text="")
    row_b.popover("USERPREF_PT_extensions_bl_pkg_filter", text="", icon='FILTER')

    row_b.separator()
    row_b.menu("USERPREF_MT_extensions_bl_pkg_settings", text="", icon='DOWNARROW_HLT')
    row_b.popover("USERPREF_PT_extensions_repos", text="", icon='PREFERENCES')
    del row, row_a, row_b

    if show_development_reports:
        show_status = bool(repo_status_text.log)
    else:
        # Only show if running and there is progress to display.
        show_status = bool(repo_status_text.log) and repo_status_text.running
        if show_status:
            show_status = False
            for ty, msg in repo_status_text.log:
                if ty == 'PROGRESS':
                    show_status = True

    if show_status:
        box = layout.box()
        # Don't clip longer names.
        row = box.split(factor=0.9, align=True)
        if repo_status_text.running:
            row.label(text=repo_status_text.title + "...", icon='INFO')
        else:
            row.label(text=repo_status_text.title, icon='INFO')
        if show_development_reports:
            rowsub = row.row(align=True)
            rowsub.alignment = 'RIGHT'
            rowsub.operator("bl_pkg.pkg_status_clear", text="", icon='X', emboss=False)
        boxsub = box.box()
        for ty, msg in repo_status_text.log:
            if ty == 'STATUS':
                boxsub.label(text=msg)
            elif ty == 'PROGRESS':
                msg_str, progress_unit, progress, progress_range = msg
                if progress <= progress_range:
                    boxsub.progress(
                        factor=progress / progress_range,
                        text="{:s}, {:s}".format(
                            sizes_as_percentage_string(progress, progress_range),
                            msg_str,
                        ),
                    )
                elif progress_unit == 'BYTE':
                    boxsub.progress(factor=0.0, text="{:s}, {:s}".format(msg_str, size_as_fmt_string(progress)))
                else:
                    # We might want to support other types.
                    boxsub.progress(factor=0.0, text="{:s}, {:d}".format(msg_str, progress))
            else:
                boxsub.label(text="{:s}: {:s}".format(ty, msg))

        # Hide when running.
        if repo_status_text.running:
            return

    extensions_panel_draw_impl(
        panel,
        context,
        wm.extension_search.lower(),
        blender_filter_by_type_map[wm.extension_type],
        wm.extension_enabled_only,
        wm.extension_installed_only,
        wm.extension_show_legacy_addons,
        show_development,
    )


class USERPREF_PT_extensions_bl_pkg_drop_url(Panel):
    bl_label = "Drop URL"

    bl_space_type = 'TOPBAR'  # dummy.
    bl_region_type = 'HEADER'
    bl_ui_units_x = 13

    # WARNING: workaround for not being able to pass arguments to a popup.
    drop_variables = None

    def draw(self, context):
        layout = self.layout

        repo_index, repo_name, pkg_id, item_remote = USERPREF_PT_extensions_bl_pkg_drop_url.drop_variables

        layout.label(text="Install Extension")
        layout.separator(type='LINE')
        layout.label(text="Do you want to install the following {:s}?".format(item_remote["type"]))

        col = layout.column(align=True)
        col.label(text="Name: {:s}".format(item_remote["name"]))
        col.label(text="Repository: {:s}".format(repo_name))
        col.label(text="Size: {:s}".format(size_as_fmt_string(item_remote["archive_size"], precision=0)))
        del col

        layout.separator()

        if item_remote["type"] == "add-on":
            wm = context.window_manager
            layout.prop(wm, "extension_enable_on_install")
            enable_on_install = wm.extension_enable_on_install
        else:
            enable_on_install = False

        layout.separator()

        row = layout.row()

        row.operator("bl_pkg.popup_cancel", text="Cancel")

        props = row.operator("bl_pkg.pkg_install", text="Install")
        props.repo_index = repo_index
        props.pkg_id = pkg_id
        props.enable_on_install = enable_on_install


class USERPREF_PT_extensions_bl_pkg_drop_file(Panel):
    bl_label = "Drop File"

    bl_space_type = 'TOPBAR'  # dummy.
    bl_region_type = 'HEADER'
    bl_ui_units_x = 13

    # WARNING: workaround for not being able to pass arguments to a popup.
    drop_variables = None

    def draw(self, context):
        layout = self.layout

        url = USERPREF_PT_extensions_bl_pkg_drop_file.drop_variables

        # TODO: this UI isn't so nice, ideally the repo can be selected with an OK button.
        # This is more complicated than it might seem as calling `bpy.ops.*` doesn't forward errors to the window-manager.
        # The API may need to be extended to better support this use-case.
        layout.operator_context = 'EXEC_DEFAULT'
        layout.label(text="Install from Disk")
        layout.separator(type='LINE')

        wm = context.window_manager
        layout.label(text="Local Repository")
        layout.prop(wm, "extension_local_repos", text="")

        # TODO: inspect the ZIP and find if the type is an add-on.
        if True:
            wm = context.window_manager
            layout.prop(wm, "extension_enable_on_install")
            enable_on_install = wm.extension_enable_on_install

        row = layout.row()

        row.operator("bl_pkg.popup_cancel", text="Cancel")

        props = row.operator("bl_pkg.pkg_install_files", text="Install")
        props.repo = wm.extension_local_repos
        props.filepath = url
        props.enable_on_install = enable_on_install


classes = (
    # Pop-overs.
    USERPREF_PT_extensions_bl_pkg_filter,
    USERPREF_MT_extensions_bl_pkg_settings,

    USERPREF_PT_extensions_bl_pkg_drop_url,
    USERPREF_PT_extensions_bl_pkg_drop_file,
)


def register():
    USERPREF_PT_addons.append(extensions_panel_draw)

    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    USERPREF_PT_addons.remove(extensions_panel_draw)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
