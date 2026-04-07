export type ActorKind = 'human' | 'agent' | 'service';
export type ActorPresenceState = 'available' | 'working' | 'finished_recently' | 'paused' | 'offline' | 'at_capacity';

interface AvatarPalette {
	surface: string;
	shell: string;
	shellMuted: string;
	face: string;
	hair: string;
	accent: string;
	accentMuted: string;
	line: string;
}

interface ActorAvatarVariant {
	palette: AvatarPalette;
	accessory: 'none' | 'visor' | 'headband' | 'badge' | 'antenna' | 'glasses' | 'cap' | 'earring';
	persona: 'human' | 'robot' | 'cat' | 'dog' | 'fox' | 'owl';
	hairStyle: 'none' | 'buzz' | 'part' | 'waves' | 'curl' | 'coily' | 'bun' | 'spikes';
	eyeShape: 'dot' | 'bar' | 'wide';
	mouthShape: 'flat' | 'smile' | 'focus';
	shellShape: 'round' | 'squircle';
}

export interface ActorViewModel {
	id: string;
	kind: ActorKind;
	displayName: string;
	subtitle?: string;
	avatarSeed: string;
	avatarStyleVersion: number;
	presenceState: ActorPresenceState;
	presenceLabel: string;
	statusAccent: string;
	avatarVariant: ActorAvatarVariant;
}

const PRESENCE_LABELS: Record<ActorPresenceState, string> = {
	available: 'Available',
	working: 'Working',
	finished_recently: 'Finished recently',
	paused: 'Paused',
	offline: 'Offline',
	at_capacity: 'At capacity',
};

const PRESENCE_ACCENTS: Record<ActorPresenceState, string> = {
	available: '#1f8a70',
	working: '#0f7c8a',
	finished_recently: '#5aa08c',
	paused: '#e49d37',
	offline: '#8c9399',
	at_capacity: '#d27c2c',
};

type AvatarPaletteEntry = { id: string; value: AvatarPalette };

const HUMAN_PALETTES: AvatarPaletteEntry[] = [
	{ id: 'human-honey', value: { surface: '#f5ece2', shell: '#7f9171', shellMuted: '#d8e1c7', face: '#f4d8c2', hair: '#3f2e26', accent: '#e07a5f', accentMuted: '#f3c0ad', line: '#2d221d' } },
	{ id: 'human-espresso', value: { surface: '#efe5dd', shell: '#6d7d95', shellMuted: '#c8d5e4', face: '#ddb090', hair: '#2f1d18', accent: '#d46a4f', accentMuted: '#efb39f', line: '#281813' } },
	{ id: 'human-deep-umber', value: { surface: '#ece5dd', shell: '#64796d', shellMuted: '#c9d8cf', face: '#8a5b44', hair: '#1d1614', accent: '#ef8f62', accentMuted: '#f6c5a8', line: '#140f0d' } },
	{ id: 'human-golden', value: { surface: '#f1e8d8', shell: '#7b8f5b', shellMuted: '#d8e4bf', face: '#c78f63', hair: '#6a4126', accent: '#3d8f7b', accentMuted: '#95cbbd', line: '#2f2218' } },
	{ id: 'human-rose', value: { surface: '#f6e8e8', shell: '#7c6d86', shellMuted: '#d9cfe2', face: '#edc0a7', hair: '#7f4a37', accent: '#cb5f78', accentMuted: '#e7a7b7', line: '#2d2027' } },
	{ id: 'human-almond', value: { surface: '#f4eee7', shell: '#8f755f', shellMuted: '#dfcfbe', face: '#c89f7d', hair: '#4d3427', accent: '#5a8fce', accentMuted: '#a8c6eb', line: '#291c16' } },
	{ id: 'human-porcelain', value: { surface: '#eef2ef', shell: '#6b8f82', shellMuted: '#c8ddd6', face: '#f0dccf', hair: '#785837', accent: '#d06d4a', accentMuted: '#f0ba9b', line: '#2b302f' } },
	{ id: 'human-ebony', value: { surface: '#ece7e2', shell: '#627489', shellMuted: '#cad7e5', face: '#5d4034', hair: '#120f0e', accent: '#ed9356', accentMuted: '#f7c8a1', line: '#110f0f' } },
];

const ROBOT_PALETTES: AvatarPaletteEntry[] = [
	{ id: 'robot-graphite', value: { surface: '#dfe8ec', shell: '#536b78', shellMuted: '#9ab0ba', face: '#bdd0d8', hair: '#354953', accent: '#59a8c4', accentMuted: '#98cedf', line: '#1e2b32' } },
	{ id: 'robot-copper', value: { surface: '#efe3d7', shell: '#9d6748', shellMuted: '#d7b8a2', face: '#d7b39b', hair: '#744731', accent: '#4b9a8f', accentMuted: '#8fc9c1', line: '#332018' } },
	{ id: 'robot-orchid', value: { surface: '#ebe6f5', shell: '#6a648a', shellMuted: '#c8c2df', face: '#cdc6e3', hair: '#46415f', accent: '#ea8b57', accentMuted: '#f6b894', line: '#27243a' } },
	{ id: 'robot-lime', value: { surface: '#e9f0dd', shell: '#667950', shellMuted: '#c2d2ab', face: '#cad5ba', hair: '#465339', accent: '#3e8ea8', accentMuted: '#93c4d4', line: '#232b1d' } },
];

const CAT_PALETTES: AvatarPaletteEntry[] = [
	{ id: 'cat-tuxedo', value: { surface: '#eef1f4', shell: '#485763', shellMuted: '#afbcc5', face: '#f1f2ef', hair: '#2c343c', accent: '#d68b4e', accentMuted: '#efc39a', line: '#1c2227' } },
	{ id: 'cat-ginger', value: { surface: '#f3e9df', shell: '#b06c3c', shellMuted: '#e0bc9f', face: '#f2c69b', hair: '#8c4e26', accent: '#4f8d86', accentMuted: '#96c4bf', line: '#352113' } },
	{ id: 'cat-lilac', value: { surface: '#efe8f2', shell: '#8a6f92', shellMuted: '#d7c4dd', face: '#dacbdf', hair: '#674f6f', accent: '#d97169', accentMuted: '#efb1aa', line: '#302435' } },
];

const DOG_PALETTES: AvatarPaletteEntry[] = [
	{ id: 'dog-caramel', value: { surface: '#f2e7dc', shell: '#967257', shellMuted: '#d9c2ae', face: '#d5a97b', hair: '#7b563a', accent: '#567da7', accentMuted: '#a6c0dd', line: '#2f2117' } },
	{ id: 'dog-shepherd', value: { surface: '#ece7df', shell: '#6d6359', shellMuted: '#c8bcaf', face: '#b98a5a', hair: '#45352a', accent: '#d48a49', accentMuted: '#f0c498', line: '#211914' } },
	{ id: 'dog-cloud', value: { surface: '#edf2f3', shell: '#72838a', shellMuted: '#c3cfd4', face: '#e0e4e4', hair: '#536168', accent: '#4c9c88', accentMuted: '#9fd0c4', line: '#243035' } },
];

const FOX_PALETTES: AvatarPaletteEntry[] = [
	{ id: 'fox-cinder', value: { surface: '#f0e7de', shell: '#995738', shellMuted: '#e0b99d', face: '#f2d1ba', hair: '#7a3f22', accent: '#4e8faa', accentMuted: '#9fc7d7', line: '#311d12' } },
	{ id: 'fox-ember', value: { surface: '#f4e6db', shell: '#ba6334', shellMuted: '#e8b996', face: '#f7dbc0', hair: '#93431f', accent: '#68985e', accentMuted: '#b0cfaa', line: '#382012' } },
];

const OWL_PALETTES: AvatarPaletteEntry[] = [
	{ id: 'owl-moss', value: { surface: '#e7ede3', shell: '#6c7858', shellMuted: '#c1ceb5', face: '#e5d8c4', hair: '#4b543e', accent: '#b66b4a', accentMuted: '#ddb19c', line: '#262c20' } },
	{ id: 'owl-slate', value: { surface: '#e8edf0', shell: '#667582', shellMuted: '#c1ccd5', face: '#ddd6c9', hair: '#4d5b68', accent: '#cf8a48', accentMuted: '#ebbe95', line: '#252d34' } },
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

function hashValue(seed: string): number {
	let hash = 2166136261;
	for (let index = 0; index < seed.length; index += 1) {
		hash ^= seed.charCodeAt(index);
		hash = Math.imul(hash, 16777619);
	}
	return hash >>> 0;
}

function pick<T>(items: readonly T[], hash: number, shift: number): T {
	return items[(hash >>> shift) % items.length]!;
}

function generateAvatarVariant(seed: string, kind: ActorKind, styleVersion = 1): ActorAvatarVariant {
	const hash = hashValue(`${styleVersion}:${kind}:${seed}`);
	const persona = pick(PERSONAS_BY_KIND[kind], hash, 1);
	const palette = pick(PALETTES_BY_PERSONA[persona], hash, 5).value;
	return {
		palette,
		accessory: kind === 'service' ? 'antenna' : pick(ACCESSORIES_BY_PERSONA[persona], hash, 9),
		persona,
		hairStyle: pick(HAIRSTYLES_BY_PERSONA[persona], hash, 13),
		eyeShape: pick(EYES_BY_PERSONA[persona], hash, 17),
		mouthShape: pick(MOUTHS_BY_PERSONA[persona], hash, 21),
		shellShape: pick(SHAPES_BY_PERSONA[persona], hash, 25),
	};
}

export function createActorViewModel(input: {
	id: string;
	kind: ActorKind;
	displayName: string;
	subtitle?: string;
	avatarSeed?: string;
	avatarStyleVersion?: number;
	presenceState?: ActorPresenceState;
}): ActorViewModel {
	const avatarStyleVersion = input.avatarStyleVersion ?? 1;
	const avatarSeed = input.avatarSeed ?? `${input.kind}:${input.id}:${input.displayName}`;
	const presenceState = input.presenceState ?? 'available';
	return {
		id: input.id,
		kind: input.kind,
		displayName: input.displayName,
		subtitle: input.subtitle,
		avatarSeed,
		avatarStyleVersion,
		presenceState,
		presenceLabel: PRESENCE_LABELS[presenceState],
		statusAccent: PRESENCE_ACCENTS[presenceState],
		avatarVariant: generateAvatarVariant(avatarSeed, input.kind, avatarStyleVersion),
	};
}

export function buildActorAvatarSvg(actor: ActorViewModel, size = 40): string {
	const variant = actor.avatarVariant;
	const radius = variant.shellShape === 'round' ? size / 2 : Math.round(size * 0.34);
	const eyeWidth = variant.eyeShape === 'bar' ? 4 : variant.eyeShape === 'wide' ? 5 : 3;
	const eyeHeight = variant.eyeShape === 'bar' ? 1.6 : 3;
	const headX = variant.persona === 'robot' ? size * 0.2 : variant.persona === 'owl' ? size * 0.18 : size * 0.24;
	const headWidth = variant.persona === 'robot' ? size * 0.6 : variant.persona === 'owl' ? size * 0.64 : size * 0.52;
	const headY = size * 0.18;
	const headHeight = variant.persona === 'owl' ? size * 0.56 : size * 0.5;
	const headRadius = variant.persona === 'robot' ? size * 0.12 : variant.persona === 'owl' ? size * 0.2 : size * 0.18;
	const mouth = variant.mouthShape === 'focus'
		? `<circle cx="${size * 0.5}" cy="${size * 0.64}" r="${size * 0.05}" fill="none" stroke="${variant.palette.line}" stroke-width="1.8" />`
		: variant.mouthShape === 'flat'
			? `<rect x="${size * 0.4}" y="${size * 0.63}" width="${size * 0.2}" height="1.8" rx="0.9" fill="${variant.palette.line}" />`
			: `<path d="M ${size * 0.39} ${size * 0.62} Q ${size * 0.5} ${size * 0.69} ${size * 0.61} ${size * 0.62}" fill="none" stroke="${variant.palette.line}" stroke-width="1.8" stroke-linecap="round" />`;
	const accessory = variant.accessory === 'visor'
		? `<rect x="${size * 0.22}" y="${size * 0.34}" width="${size * 0.56}" height="${size * 0.09}" rx="${size * 0.045}" fill="${variant.palette.accent}" fill-opacity="0.92" />`
		: variant.accessory === 'headband'
			? `<rect x="${size * 0.14}" y="${size * 0.18}" width="${size * 0.72}" height="${size * 0.07}" rx="${size * 0.035}" fill="${variant.palette.accent}" />`
			: variant.accessory === 'badge'
				? `<circle cx="${size * 0.78}" cy="${size * 0.78}" r="${size * 0.09}" fill="${variant.palette.accent}" stroke="${variant.palette.line}" stroke-opacity="0.18" stroke-width="1.5" />`
				: variant.accessory === 'antenna'
					? `<path d="M ${size * 0.5} ${size * 0.06} L ${size * 0.5} ${size * 0.18}" stroke="${variant.palette.accent}" stroke-width="2" stroke-linecap="round" /><circle cx="${size * 0.5}" cy="${size * 0.05}" r="${size * 0.05}" fill="${variant.palette.accent}" />`
					: variant.accessory === 'glasses'
						? `<rect x="${size * 0.24}" y="${size * 0.38}" width="${size * 0.16}" height="${size * 0.11}" rx="${size * 0.05}" fill="none" stroke="${variant.palette.line}" stroke-width="1.5" /><rect x="${size * 0.6}" y="${size * 0.38}" width="${size * 0.16}" height="${size * 0.11}" rx="${size * 0.05}" fill="none" stroke="${variant.palette.line}" stroke-width="1.5" /><path d="M ${size * 0.4} ${size * 0.43} H ${size * 0.6}" stroke="${variant.palette.line}" stroke-width="1.5" />`
						: variant.accessory === 'cap'
							? `<path d="M ${size * 0.18} ${size * 0.24} Q ${size * 0.5} ${size * 0.06} ${size * 0.82} ${size * 0.24} V ${size * 0.3} H ${size * 0.18} Z" fill="${variant.palette.accent}" /><path d="M ${size * 0.56} ${size * 0.28} Q ${size * 0.74} ${size * 0.3} ${size * 0.84} ${size * 0.36}" stroke="${variant.palette.accent}" stroke-width="3" stroke-linecap="round" />`
							: variant.accessory === 'earring'
								? `<path d="M ${size * 0.74} ${size * 0.54} a ${size * 0.04} ${size * 0.05} 0 1 0 ${size * 0.08} 0" fill="none" stroke="${variant.palette.accent}" stroke-width="1.8" />`
								: '';
	const hair = variant.hairStyle === 'none'
		? ''
		: variant.hairStyle === 'buzz'
			? `<rect x="${headX + size * 0.02}" y="${headY + size * 0.02}" width="${headWidth - size * 0.04}" height="${size * 0.1}" rx="${size * 0.05}" fill="${variant.palette.hair}" />`
			: variant.hairStyle === 'bun'
				? `<rect x="${headX}" y="${headY}" width="${headWidth}" height="${size * 0.14}" rx="${size * 0.07}" fill="${variant.palette.hair}" /><circle cx="${size * 0.5}" cy="${size * 0.12}" r="${size * 0.08}" fill="${variant.palette.hair}" />`
				: variant.hairStyle === 'spikes'
					? `<path d="M ${headX} ${headY + size * 0.1} L ${headX + size * 0.06} ${headY} L ${headX + size * 0.12} ${headY + size * 0.1} L ${headX + size * 0.18} ${headY + size * 0.02} L ${headX + size * 0.24} ${headY + size * 0.1} L ${headX + size * 0.3} ${headY} L ${headX + size * 0.36} ${headY + size * 0.1} L ${headX + size * 0.42} ${headY + size * 0.02} L ${headX + size * 0.48} ${headY + size * 0.1}" fill="${variant.palette.hair}" />`
					: `<rect x="${headX}" y="${headY}" width="${headWidth}" height="${size * 0.14}" rx="${size * 0.07}" fill="${variant.palette.hair}" />`;
	const ears = variant.persona === 'cat' || variant.persona === 'fox' || variant.persona === 'owl'
		? `<path d="M ${size * 0.28} ${size * 0.08} L ${size * 0.36} ${size * 0.24} H ${size * 0.2} Z" fill="${variant.palette.hair}" /><path d="M ${size * 0.72} ${size * 0.08} L ${size * 0.8} ${size * 0.24} H ${size * 0.64} Z" fill="${variant.palette.hair}" />`
		: variant.persona === 'dog'
			? `<rect x="${size * 0.16}" y="${size * 0.22}" width="${size * 0.14}" height="${size * 0.22}" rx="${size * 0.08}" fill="${variant.palette.hair}" transform="rotate(12 ${size * 0.16} ${size * 0.22})" /><rect x="${size * 0.7}" y="${size * 0.22}" width="${size * 0.14}" height="${size * 0.22}" rx="${size * 0.08}" fill="${variant.palette.hair}" transform="rotate(-12 ${size * 0.7} ${size * 0.22})" />`
			: '';
	const snout = variant.persona === 'cat' || variant.persona === 'dog' || variant.persona === 'fox'
		? `<ellipse cx="${size * 0.5}" cy="${size * 0.64}" rx="${size * 0.12}" ry="${size * 0.08}" fill="white" fill-opacity="0.34" />`
		: variant.persona === 'owl'
			? `<path d="M ${size * 0.5} ${size * 0.66} L ${size * 0.43} ${size * 0.56} H ${size * 0.57} Z" fill="${variant.palette.accent}" />`
			: '';
	const kindMark = actor.kind === 'human'
		? ''
		: `<circle cx="${size * 0.82}" cy="${size * 0.18}" r="${size * 0.05}" fill="${variant.palette.accent}" /><circle cx="${size * 0.72}" cy="${size * 0.22}" r="${size * 0.035}" fill="${variant.palette.line}" fill-opacity="0.7" />`;

	return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" fill="none">
		<rect width="${size}" height="${size}" rx="${radius}" fill="${variant.palette.surface}" />
		<circle cx="${size * 0.28}" cy="${size * 0.24}" r="${size * 0.22}" fill="white" fill-opacity="0.14" />
		<rect x="${size * 0.22}" y="${size * 0.66}" width="${size * 0.56}" height="${size * 0.24}" rx="${size * 0.12}" fill="${variant.palette.shell}" />
		${variant.persona === 'robot'
			? `<rect x="${size * 0.18}" y="${size * 0.64}" width="${size * 0.64}" height="${size * 0.26}" rx="${size * 0.08}" fill="${variant.palette.shell}" />`
			: ''}
		${ears}
		<rect x="${headX}" y="${headY}" width="${headWidth}" height="${headHeight}" rx="${headRadius}" fill="${variant.palette.face}" stroke="${variant.palette.line}" stroke-opacity="0.12" stroke-width="1.5" />
		${hair}
		<rect x="${size * 0.36}" y="${size * 0.46}" width="${eyeWidth}" height="${eyeHeight}" rx="${eyeHeight / 2}" fill="${variant.palette.line}" />
		<rect x="${size * 0.58}" y="${size * 0.46}" width="${eyeWidth}" height="${eyeHeight}" rx="${eyeHeight / 2}" fill="${variant.palette.line}" />
		${snout}
		${mouth}
		${accessory}
		${kindMark}
		<circle cx="${size - 6}" cy="${size - 6}" r="5" fill="${actor.statusAccent}" stroke="${variant.palette.surface}" stroke-width="2" />
	</svg>`;
}

export function buildActorAvatarDataUri(actor: ActorViewModel, size = 40): string {
	return `data:image/svg+xml;utf8,${encodeURIComponent(buildActorAvatarSvg(actor, size))}`;
}

export function buildActorAvatarHtml(actor: ActorViewModel, size = 44): string {
	const dataUri = buildActorAvatarDataUri(actor, size);
	return `<span style="display:inline-flex;align-items:center;justify-content:center;width:${size}px;height:${size}px;border-radius:${Math.round(size * 0.34)}px;overflow:hidden;border:1px solid color-mix(in srgb, ${actor.avatarVariant.palette.line} 18%, transparent);background:${actor.avatarVariant.palette.surface};">
		<img src="${dataUri}" alt="" width="${size}" height="${size}" style="display:block;width:${size}px;height:${size}px;" />
	</span>`;
}
