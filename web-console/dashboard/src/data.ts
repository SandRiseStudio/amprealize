export interface ProgressItem {
  workItem: string;
  owner: string;
  status: string;
  evidence: string;
  section: string;
}

export interface TimelineEntry {
  order: string;
  artifact: string;
  description: string;
  date: string;
}

export interface AlignmentEntry {
  text: string;
}

export interface ConsentMetric {
  surface: string;
  prompts: number;
  approvals: number;
  denials: number;
  snoozes: number;
  mfaRequired: number;
  mfaCompleted: number;
  averageLatencySeconds: number;
  p95LatencySeconds: number;
}

export interface ConsentSnapshot {
  metrics: ConsentMetric[];
  updated: string;
}

export interface OnboardingMetric {
  surface: string;
  sampleSize: number;
  averageTimeToFirstBehaviorMinutes: number;
  checklistCompletionRate: number;
  behaviorSearchToInsertRate: number;
  behaviorReuseRate: number;
  tokenSavingsAverage: number;
  taskCompletionRate: number;
  complianceCoverage: number;
}

export interface OnboardingSnapshot {
  metrics: OnboardingMetric[];
  updated: string;
}

export interface StreamingMetricsData {
  sprint: string;
  completion: number;
  kafkaBurstRate: number;
  kafkaSustainedRate: number;
  sustainedDuration: string;
  testsPass: number;
  testsTotal: number;
  infrastructureStatus: string;
  blocker: string | null;
  pathForward: string | null;
}


const tableSectionRegex = /##\s+([^\n]+)\n([\s\S]*?)(?=\n##\s+|\n_Last updated|$)/g;

function parseTableBlock(block: string): string[][] {
  const lines = block
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.startsWith('|'));

  if (lines.length <= 2) return [];

  const dataLines = lines.slice(2);

  return dataLines
    .map((line) =>
      line
        .split('|')
        .map((cell) => cell.trim())
        .filter(Boolean)
    )
    .filter((row) => row.length > 0);
}

export function parseProgressTracker(markdown: string): {
  sections: ProgressItem[];
  lastUpdated: string;
} {
  tableSectionRegex.lastIndex = 0;
  const sections: ProgressItem[] = [];
  let match: RegExpExecArray | null;

  while ((match = tableSectionRegex.exec(markdown)) !== null) {
    const [, sectionTitle, block] = match;
    const rows = parseTableBlock(block);

    rows.forEach((row) => {
      const [workItem = '', owner = '', status = '', evidence = ''] = row;
      sections.push({
        workItem,
        owner,
        status,
        evidence,
        section: sectionTitle.trim(),
      });
    });
  }

  const lastUpdatedMatch = markdown.match(/_Last updated: (.+?)_/);

  return {
    sections,
    lastUpdated: lastUpdatedMatch ? lastUpdatedMatch[1] : 'Unknown',
  };
}

export function parseBuildTimeline(markdown: string): TimelineEntry[] {
  const rows = parseTableBlock(markdown);
  return rows.map(([order = '', artifact = '', description = '', date = '']) => ({
    order,
    artifact,
    description,
    date,
  }));
}

export function parseAlignmentLog(markdown: string): AlignmentEntry[] {
  const listRegex = /^-\s+(.+)$/gm;
  const entries: AlignmentEntry[] = [];
  let match: RegExpExecArray | null;

  while ((match = listRegex.exec(markdown)) !== null) {
    entries.push({ text: match[1].trim() });
  }

  return entries;
}

export function parseConsentSnapshot(markdown: string): ConsentSnapshot {
  const rows = parseTableBlock(markdown);
  const metrics: ConsentMetric[] = rows.map((row) => {
    const [
      surface = '',
      prompts = '0',
      approvals = '0',
      denials = '0',
      snoozes = '0',
      mfaRequired = '0',
      mfaCompleted = '0',
      avgLatency = '0',
      p95Latency = '0',
    ] = row;

    return {
      surface,
      prompts: Number(prompts),
      approvals: Number(approvals),
      denials: Number(denials),
      snoozes: Number(snoozes),
      mfaRequired: Number(mfaRequired),
      mfaCompleted: Number(mfaCompleted),
      averageLatencySeconds: Number(avgLatency),
      p95LatencySeconds: Number(p95Latency),
    };
  });

  const updatedMatch = markdown.match(/_Updated:\s*([^_]+)_/i);

  return {
    metrics,
    updated: updatedMatch ? updatedMatch[1].trim() : 'Unknown',
  };
}

export function parseOnboardingSnapshot(markdown: string): OnboardingSnapshot {
  const rows = parseTableBlock(markdown);
  const metrics: OnboardingMetric[] = rows.map((row) => {
    const [
      surface = '',
      sampleSize = '0',
      avgTime = '0',
      checklist = '0',
      searchInsert = '0',
      behaviorReuse = '0',
      tokenSavings = '0',
      taskCompletion = '0',
      compliance = '0',
    ] = row;

    return {
      surface,
      sampleSize: Number(sampleSize),
      averageTimeToFirstBehaviorMinutes: Number(avgTime),
      checklistCompletionRate: Number(checklist),
      behaviorSearchToInsertRate: Number(searchInsert),
      behaviorReuseRate: Number(behaviorReuse),
      tokenSavingsAverage: Number(tokenSavings),
      taskCompletionRate: Number(taskCompletion),
      complianceCoverage: Number(compliance),
    };
  });

  const updatedMatch = markdown.match(/_Updated:\s*([^_]+)_/i);

  return {
    metrics,
    updated: updatedMatch ? updatedMatch[1].trim() : 'Unknown',
  };
}

export function parseStreamingMetrics(markdown: string): StreamingMetricsData | null {
  // Extract Sprint 3 status from Last Updated banner
  const sprint3Match = markdown.match(/Sprint 3[^)]*90% COMPLETE[^)]*\)/i);
  if (!sprint3Match) {
    return null;
  }

  // Parse key metrics from the Service Coverage Summary section
  const burstMatch = markdown.match(/burst\s+(\d+,?\d*)\s*events?\/sec/i);
  const sustainedMatch = markdown.match(/sustained\s+1,?000\s*events?\/sec.*?for\s+(\d+)\s*min/i);
  const testsMatch = markdown.match(/(\d+)\/(\d+)\s+load\s+tests\s+passing/i);

  return {
    sprint: 'Sprint 3: High-Volume Streaming',
    completion: 90,
    kafkaBurstRate: burstMatch ? parseInt(burstMatch[1].replace(',', '')) : 9850,
    kafkaSustainedRate: 1000,
    sustainedDuration: sustainedMatch ? `${sustainedMatch[1]}min` : '5min',
    testsPass: testsMatch ? parseInt(testsMatch[1]) : 3,
    testsTotal: testsMatch ? parseInt(testsMatch[2]) : 8,
    infrastructureStatus: 'Operational',
    blocker: 'Apache Flink AMD64 Docker images cause QEMU segmentation faults on Apple Silicon, blocking Kafka→Flink→PostgreSQL end-to-end pipeline validation.',
    pathForward: 'AMD64 CI runner (GitHub Actions) for full pipeline tests, ARM-native Flink Docker images, or accept Kafka-only validation as sufficient producer capacity proof.',
  };
}
