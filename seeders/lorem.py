"""Deterministic lorem ipsum, for filling test videos.

Deterministic on purpose: every function takes a ``seed``, so re-running a seeder
produces byte-identical text. That keeps the video seeder idempotent (it matches an
existing video by its premise) and makes a bug reproducible from the same command.

Sentence and paragraph lengths vary, because a wall of uniform-length paragraphs
does not exercise the layout the way real prose does.
"""
import random

# The conventional opening, so the first paragraph reads as recognisable filler.
OPENING = (
    "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor "
    "incididunt ut labore et dolore magna aliqua"
).split()

_WORDS = (
    "a ac accumsan ad adipiscing aenean aliqua aliquam aliquet amet ante aptent arcu "
    "at auctor augue bibendum blandit class commodo condimentum congue consectetur "
    "consequat conubia convallis cras cubilia cursus dapibus diam dictum dictumst "
    "dignissim dis dolor dolore donec dui duis efficitur egestas eget eleifend "
    "elementum elit enim erat eros est et etiam eu euismod ex facilisi facilisis "
    "fames faucibus felis fermentum feugiat fringilla fusce gravida habitant "
    "habitasse hac hendrerit himenaeos iaculis id imperdiet in inceptos integer "
    "interdum ipsum justo lacinia lacus laoreet lectus leo libero ligula litora "
    "lobortis lorem luctus maecenas magna magnis malesuada massa mattis mauris "
    "maximus metus mi molestie mollis montes morbi mus nam nascetur natoque nec "
    "neque netus nibh nisi nisl non nostra nulla nullam nunc odio orci ornare "
    "parturient pellentesque penatibus per pharetra phasellus placerat platea "
    "porta porttitor posuere potenti praesent pretium primis proin pulvinar purus "
    "quam quis quisque rhoncus ridiculus risus rutrum sagittis sapien scelerisque "
    "sed sem semper senectus sit sociosqu sodales sollicitudin suscipit suspendisse "
    "taciti tellus tempor tempus tincidunt torquent tortor tristique turpis "
    "ullamcorper ultrices ultricies urna ut varius vehicula vel velit venenatis "
    "vestibulum vitae vivamus viverra volutpat vulputate"
).split()

_TITLE_WORDS = (
    "lorem ipsum dolor amet consectetur adipiscing elit tempor labore dolore magna "
    "aliqua veniam nostrud aliquip commodo aute irure reprehenderit voluptate "
    "cillum fugiat pariatur excepteur occaecat cupidatat proident culpa officia "
    "deserunt mollit anim laborum"
).split()


def _rng(seed):
    return random.Random(seed)


def _sentence(rng, opening=None):
    length = rng.randint(8, 20)
    if opening:
        picked = list(opening[:length])
        while len(picked) < length:
            picked.append(rng.choice(_WORDS))
    else:
        picked = [rng.choice(_WORDS) for _ in range(length)]

    # A comma or two, placed away from both ends so it never reads as a typo. Skipped
    # for the opening sentence: a comma dropped into "lorem ipsum dolor sit amet"
    # breaks the phrase people recognise as filler.
    if not opening:
        for _ in range(rng.randint(0, 2)):
            if length > 8:
                at = rng.randint(3, length - 4)
                if not picked[at].endswith(","):
                    picked[at] += ","

    text = " ".join(picked)
    return text[0].upper() + text[1:] + "."


def paragraph(seed, words=90, opening=False):
    """One paragraph of roughly ``words`` words."""
    rng = _rng(seed)
    out, count = [], 0
    while count < words:
        sentence = _sentence(rng, OPENING if (opening and not out) else None)
        out.append(sentence)
        count += len(sentence.split())
    return " ".join(out)


def paragraphs(seed, words=300, opening=False):
    """Paragraphs totalling roughly ``words`` words, of varying length.

    Returns a list, so a caller can join them however it likes — the video seeder
    joins with a blank line, matching how the split step slices a script.
    """
    rng = _rng(seed)
    out, remaining, n = [], words, 0
    while remaining > 0:
        size = min(remaining, rng.randint(60, 120))
        out.append(paragraph(seed * 1000 + n, size, opening=opening and n == 0))
        remaining -= size
        n += 1
    return out


def title(seed, words=4):
    rng = _rng(seed)
    picked = [rng.choice(_TITLE_WORDS) for _ in range(words)]
    return " ".join(w.capitalize() for w in picked)


def sentence(seed):
    return _sentence(_rng(seed))


def hashtags(seed, count=5):
    rng = _rng(seed)
    return ["#" + rng.choice(_TITLE_WORDS).capitalize() for _ in range(count)]
