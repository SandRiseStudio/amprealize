import type { ActorAvatarVariant, ActorKind, AvatarPalette } from '../types/actor';

type AvatarPaletteEntry = { id: string; value: AvatarPalette };

const HUMAN_PALETTES: AvatarPaletteEntry[] = [
  {
    id: 'human-honey',
    value: {
      surface: '#f5ece2',
      shell: '#7f9171',
      shellMuted: '#d8e1c7',
      face: '#f4d8c2',
      hair: '#3f2e26',
      accent: '#e07a5f',
      accentMuted: '#f3c0ad',
      line: '#2d221d',
    },
  },
  {
    id: 'human-espresso',
    value: {
      surface: '#efe5dd',
      shell: '#6d7d95',
      shellMuted: '#c8d5e4',
      face: '#ddb090',
      hair: '#2f1d18',
      accent: '#d46a4f',
      accentMuted: '#efb39f',
      line: '#281813',
    },
  },
  {
    id: 'human-deep-umber',
    value: {
      surface: '#ece5dd',
      shell: '#64796d',
      shellMuted: '#c9d8cf',
      face: '#8a5b44',
      hair: '#1d1614',
      accent: '#ef8f62',
      accentMuted: '#f6c5a8',
      line: '#140f0d',
    },
  },
  {
    id: 'human-golden',
    value: {
      surface: '#f1e8d8',
      shell: '#7b8f5b',
      shellMuted: '#d8e4bf',
      face: '#c78f63',
      hair: '#6a4126',
      accent: '#3d8f7b',
      accentMuted: '#95cbbd',
      line: '#2f2218',
    },
  },
  {
    id: 'human-rose',
    value: {
      surface: '#f6e8e8',
      shell: '#7c6d86',
      shellMuted: '#d9cfe2',
      face: '#edc0a7',
      hair: '#7f4a37',
      accent: '#cb5f78',
      accentMuted: '#e7a7b7',
      line: '#2d2027',
    },
  },
  {
    id: 'human-almond',
    value: {
      surface: '#f4eee7',
      shell: '#8f755f',
      shellMuted: '#dfcfbe',
      face: '#c89f7d',
      hair: '#4d3427',
      accent: '#5a8fce',
      accentMuted: '#a8c6eb',
      line: '#291c16',
    },
  },
  {
    id: 'human-porcelain',
    value: {
      surface: '#eef2ef',
      shell: '#6b8f82',
      shellMuted: '#c8ddd6',
      face: '#f0dccf',
      hair: '#785837',
      accent: '#d06d4a',
      accentMuted: '#f0ba9b',
      line: '#2b302f',
    },
  },
  {
    id: 'human-ebony',
    value: {
      surface: '#ece7e2',
      shell: '#627489',
      shellMuted: '#cad7e5',
      face: '#5d4034',
      hair: '#120f0e',
      accent: '#ed9356',
      accentMuted: '#f7c8a1',
      line: '#110f0f',
    },
  },
];

const ROBOT_PALETTES: AvatarPaletteEntry[] = [
  {
    id: 'robot-graphite',
    value: {
      surface: '#dfe8ec',
      shell: '#536b78',
      shellMuted: '#9ab0ba',
      face: '#bdd0d8',
      hair: '#354953',
      accent: '#59a8c4',
      accentMuted: '#98cedf',
      line: '#1e2b32',
    },
  },
  {
    id: 'robot-copper',
    value: {
      surface: '#efe3d7',
      shell: '#9d6748',
      shellMuted: '#d7b8a2',
      face: '#d7b39b',
      hair: '#744731',
      accent: '#4b9a8f',
      accentMuted: '#8fc9c1',
      line: '#332018',
    },
  },
  {
    id: 'robot-orchid',
    value: {
      surface: '#ebe6f5',
      shell: '#6a648a',
      shellMuted: '#c8c2df',
      face: '#cdc6e3',
      hair: '#46415f',
      accent: '#ea8b57',
      accentMuted: '#f6b894',
      line: '#27243a',
    },
  },
  {
    id: 'robot-lime',
    value: {
      surface: '#e9f0dd',
      shell: '#667950',
      shellMuted: '#c2d2ab',
      face: '#cad5ba',
      hair: '#465339',
      accent: '#3e8ea8',
      accentMuted: '#93c4d4',
      line: '#232b1d',
    },
  },
];

const CAT_PALETTES: AvatarPaletteEntry[] = [
  {
    id: 'cat-tuxedo',
    value: {
      surface: '#eef1f4',
      shell: '#485763',
      shellMuted: '#afbcc5',
      face: '#f1f2ef',
      hair: '#2c343c',
      accent: '#d68b4e',
      accentMuted: '#efc39a',
      line: '#1c2227',
    },
  },
  {
    id: 'cat-ginger',
    value: {
      surface: '#f3e9df',
      shell: '#b06c3c',
      shellMuted: '#e0bc9f',
      face: '#f2c69b',
      hair: '#8c4e26',
      accent: '#4f8d86',
      accentMuted: '#96c4bf',
      line: '#352113',
    },
  },
  {
    id: 'cat-lilac',
    value: {
      surface: '#efe8f2',
      shell: '#8a6f92',
      shellMuted: '#d7c4dd',
      face: '#dacbdf',
      hair: '#674f6f',
      accent: '#d97169',
      accentMuted: '#efb1aa',
      line: '#302435',
    },
  },
];

const DOG_PALETTES: AvatarPaletteEntry[] = [
  {
    id: 'dog-caramel',
    value: {
      surface: '#f2e7dc',
      shell: '#967257',
      shellMuted: '#d9c2ae',
      face: '#d5a97b',
      hair: '#7b563a',
      accent: '#567da7',
      accentMuted: '#a6c0dd',
      line: '#2f2117',
    },
  },
  {
    id: 'dog-shepherd',
    value: {
      surface: '#ece7df',
      shell: '#6d6359',
      shellMuted: '#c8bcaf',
      face: '#b98a5a',
      hair: '#45352a',
      accent: '#d48a49',
      accentMuted: '#f0c498',
      line: '#211914',
    },
  },
  {
    id: 'dog-cloud',
    value: {
      surface: '#edf2f3',
      shell: '#72838a',
      shellMuted: '#c3cfd4',
      face: '#e0e4e4',
      hair: '#536168',
      accent: '#4c9c88',
      accentMuted: '#9fd0c4',
      line: '#243035',
    },
  },
];

const FOX_PALETTES: AvatarPaletteEntry[] = [
  {
    id: 'fox-cinder',
    value: {
      surface: '#f0e7de',
      shell: '#995738',
      shellMuted: '#e0b99d',
      face: '#f2d1ba',
      hair: '#7a3f22',
      accent: '#4e8faa',
      accentMuted: '#9fc7d7',
      line: '#311d12',
    },
  },
  {
    id: 'fox-ember',
    value: {
      surface: '#f4e6db',
      shell: '#ba6334',
      shellMuted: '#e8b996',
      face: '#f7dbc0',
      hair: '#93431f',
      accent: '#68985e',
      accentMuted: '#b0cfaa',
      line: '#382012',
    },
  },
];

const OWL_PALETTES: AvatarPaletteEntry[] = [
  {
    id: 'owl-moss',
    value: {
      surface: '#e7ede3',
      shell: '#6c7858',
      shellMuted: '#c1ceb5',
      face: '#e5d8c4',
      hair: '#4b543e',
      accent: '#b66b4a',
      accentMuted: '#ddb19c',
      line: '#262c20',
    },
  },
  {
    id: 'owl-slate',
    value: {
      surface: '#e8edf0',
      shell: '#667582',
      shellMuted: '#c1ccd5',
      face: '#ddd6c9',
      hair: '#4d5b68',
      accent: '#cf8a48',
      accentMuted: '#ebbe95',
      line: '#252d34',
    },
  },
];

const PERSONAS_BY_KIND: Record<ActorKind, ActorAvatarVariant['persona'][]> = {
  human: ['human'],
  agent: ['robot', 'cat', 'dog', 'fox', 'owl'],
  service: ['robot'],
};

const PALETTES_BY_PERSONA: Record<ActorAvatarVariant['persona'], AvatarPaletteEntry[]> = {
  human: HUMAN_PALETTES,
  robot: ROBOT_PALETTES,
  cat: CAT_PALETTES,
  dog: DOG_PALETTES,
  fox: FOX_PALETTES,
  owl: OWL_PALETTES,
};

const ACCESSORIES_BY_PERSONA: Record<ActorAvatarVariant['persona'], ActorAvatarVariant['accessory'][]> = {
  human: ['none', 'headband', 'badge', 'glasses', 'cap', 'earring'],
  robot: ['none', 'visor', 'badge', 'antenna'],
  cat: ['none', 'headband', 'badge', 'glasses', 'cap'],
  dog: ['none', 'badge', 'cap', 'headband'],
  fox: ['none', 'badge', 'headband', 'glasses'],
  owl: ['none', 'badge', 'glasses', 'cap'],
};

const HAIRSTYLES_BY_PERSONA: Record<ActorAvatarVariant['persona'], ActorAvatarVariant['hairStyle'][]> = {
  human: ['buzz', 'part', 'waves', 'curl', 'coily', 'bun'],
  robot: ['none', 'spikes'],
  cat: ['none'],
  dog: ['none'],
  fox: ['none'],
  owl: ['none'],
};

const SHAPES_BY_PERSONA: Record<ActorAvatarVariant['persona'], ActorAvatarVariant['shellShape'][]> = {
  human: ['round', 'squircle'],
  robot: ['squircle', 'round'],
  cat: ['round'],
  dog: ['round', 'squircle'],
  fox: ['squircle', 'round'],
  owl: ['round'],
};

const EYES_BY_PERSONA: Record<ActorAvatarVariant['persona'], ActorAvatarVariant['eyeShape'][]> = {
  human: ['dot', 'bar', 'wide'],
  robot: ['bar', 'wide', 'dot'],
  cat: ['bar', 'wide'],
  dog: ['dot', 'wide'],
  fox: ['bar', 'wide'],
  owl: ['wide', 'dot'],
};

const MOUTHS_BY_PERSONA: Record<ActorAvatarVariant['persona'], ActorAvatarVariant['mouthShape'][]> = {
  human: ['flat', 'smile', 'focus'],
  robot: ['flat', 'focus', 'smile'],
  cat: ['smile', 'focus', 'flat'],
  dog: ['smile', 'flat'],
  fox: ['focus', 'smile', 'flat'],
  owl: ['flat', 'focus'],
};

const EYES: ActorAvatarVariant['eyeShape'][] = ['dot', 'bar', 'wide'];
const MOUTHS: ActorAvatarVariant['mouthShape'][] = ['flat', 'smile', 'focus'];
const SHAPES: ActorAvatarVariant['shellShape'][] = ['round', 'squircle'];
const SCENE_ACCENTS: ActorAvatarVariant['sceneAccent'][] = ['desk', 'idle', 'sleep'];

function hashValue(seed: string): number {
  let hash = 2166136261;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function pick<T>(items: T[], hash: number, shift: number): T {
  return items[(hash >>> shift) % items.length]!;
}

export function generateAvatarVariant(
  seed: string,
  kind: ActorKind,
  styleVersion = 1,
): ActorAvatarVariant {
  const hash = hashValue(`${styleVersion}:${kind}:${seed}`);
  const persona = pick(PERSONAS_BY_KIND[kind], hash, 1);
  const palette = pick(PALETTES_BY_PERSONA[persona], hash, 5);
  const accessory = kind === 'service'
    ? 'antenna'
    : pick(ACCESSORIES_BY_PERSONA[persona], hash, 9);
  const hairStyle = pick(HAIRSTYLES_BY_PERSONA[persona], hash, 13);
  const sceneAccent: ActorAvatarVariant['sceneAccent'] =
    kind === 'human'
      ? pick(['desk', 'idle'] as const, hash, 11)
      : pick(SCENE_ACCENTS, hash, 11);

  return {
    paletteId: palette.id,
    palette: palette.value,
    accessory,
    persona,
    hairStyle,
    eyeShape: pick(EYES_BY_PERSONA[persona] ?? EYES, hash, 17),
    mouthShape: pick(MOUTHS_BY_PERSONA[persona] ?? MOUTHS, hash, 21),
    shellShape: pick(SHAPES_BY_PERSONA[persona] ?? SHAPES, hash, 25),
    spriteSeed: hash,
    sceneAccent,
  };
}
