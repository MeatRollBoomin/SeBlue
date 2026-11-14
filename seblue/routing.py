"""Pure helpers for rebuilding the selected listener target list."""

from __future__ import annotations


def listener_targets(selected_ids, devices, source_id):
    """Return connected selected endpoints, keeping selection IDs untouched."""
    names_by_id = {device.id: device.name for device in devices}
    return [(device_id, names_by_id[device_id])
            for device_id in sorted(selected_ids)
            if device_id in names_by_id and device_id != source_id]
