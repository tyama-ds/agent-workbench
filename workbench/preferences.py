"""How the human likes the screen to look: kept beside the settings, changeable at any time.

These are not settings of the work (models, folders, limits): they change
nothing an agent does, are not part of a settings backup, and can be saved
while a team is running. At present: the manner the faces are shown in, and
whether the anime pictures are in use.
"""
import json
import os
from pathlib import Path

DEFAULT = {'face_style': 'auto', 'face_anime': False}
FACE_STYLES = ('auto', 'flat', 'real', 'anime')


def checked(value) -> dict:
    """The value as it is kept: exactly the known keys, of the known kinds."""
    if not isinstance(value, dict) or set(value) != set(DEFAULT):
        raise ValueError('preferences: face_style と face_anime が必要です')
    if value['face_style'] not in FACE_STYLES:
        raise ValueError('preferences.face_style: auto, flat, real, anime のいずれかです')
    if type(value['face_anime']) is not bool:
        raise ValueError('preferences.face_anime: bool が必要です')
    # The anime pictures are used only where they were ticked: a choice of them without the tick does not stand.
    style = 'auto' if value['face_style'] == 'anime' and not value['face_anime'] else value['face_style']
    return {'face_style': style, 'face_anime': value['face_anime']}


class Preferences:
    def __init__(self, directory: Path):
        self.path = Path(directory) / 'ui-preferences.json'
        self.value = dict(DEFAULT)
        try:
            self.value = checked(json.loads(self.path.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            pass  # none saved yet, or not readable as preferences: the defaults (anime not in use)

    def save(self, value) -> dict:
        value = checked(value)
        temporary = self.path.with_name(self.path.name + '.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, self.path)
        self.value = value
        return dict(value)
