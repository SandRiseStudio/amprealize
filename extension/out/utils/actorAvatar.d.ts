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
export declare function createActorViewModel(input: {
    id: string;
    kind: ActorKind;
    displayName: string;
    subtitle?: string;
    avatarSeed?: string;
    avatarStyleVersion?: number;
    presenceState?: ActorPresenceState;
}): ActorViewModel;
export declare function buildActorAvatarSvg(actor: ActorViewModel, size?: number): string;
export declare function buildActorAvatarDataUri(actor: ActorViewModel, size?: number): string;
export declare function buildActorAvatarHtml(actor: ActorViewModel, size?: number): string;
export {};
//# sourceMappingURL=actorAvatar.d.ts.map
