# Modern Web UI Design & Architecture

> **Status:** Epic 13 - Multi-Tenant Platform
> **Author:** Amprealize Platform Team
> **Created:** 2025-12-02
> **Last Updated:** 2025-12-02


> **2026-1-09: Please refer to COLLAB_SAAS_REQUIREMENTS.md for updated full feature requirements.**

## Table of Contents

- [Overview](#overview)
- [Technology Stack](#technology-stack)
- [Architecture](#architecture)
- [Page Layouts](#page-layouts)
- [Component Library](#component-library)
- [State Management](#state-management)
- [Real-Time Features](#real-time-features)
- [Responsive Design](#responsive-design)
- [Accessibility](#accessibility)
- [Performance Optimization](#performance-optimization)
- [Development Workflow](#development-workflow)

---

## Overview

The Amprealize web UI is a modern, real-time collaborative platform featuring:

- **Multi-tenant organization management** with project workspaces
- **Kanban-style agile boards** with drag-and-drop
- **Real-time collaboration** via WebSocket
- **Agent execution monitoring** with live progress updates
- **Behavior management** with visual editors
- **Billing & usage dashboards** with Stripe integration

### Design Principles

1. **Real-time First** - All collaborative features update instantly via WebSocket
2. **Agent-Centric UX** - Agents are visible, assignable members with clear status
3. **Progressive Enhancement** - Core features work without JS, enhanced with interactivity
4. **Mobile-Responsive** - Full feature parity on mobile devices
5. **Accessibility** - WCAG AA compliance, keyboard navigation, screen reader support

---

## Technology Stack

### Frontend Framework

**Preact 10.x** + **Vite 5.x** - Fast, lightweight React alternative

**Why Preact + Vite?**
- 3KB runtime - significantly lighter than React
- Compatible with React ecosystem (preact/compat)
- Lightning-fast HMR with Vite
- Existing web-console already uses this stack
- TypeScript first-class support
- SWC for fast builds

### UI Library

**Tailwind CSS** + **shadcn/ui** components

**Why shadcn/ui?**
- Copy-paste component source (not a dependency)
- Built on Radix UI primitives (accessibility built-in)
- Fully customizable with Tailwind
- TypeScript native
- Beautiful, modern design system

### State Management

**Zustand** for client state + **TanStack Query** (React Query) for server state

**Why Zustand + TanStack Query?**
- Zustand: Minimal boilerplate, hook-based, no context providers, works perfectly with Preact
- TanStack Query: Automatic caching, background refetching, optimistic updates
- Combined: Perfect separation of client vs server state
- Both libraries are framework-agnostic and Preact-compatible

### Real-Time

**Socket.IO** client for WebSocket connections

**Authentication**

**Custom auth client** with OAuth providers + JWT token management

**Why custom auth?**
- NextAuth.js is Next.js-specific
- Direct integration with Amprealize's existing AgentAuthService
- OAuth device flow + GitHub/Google providers
- JWT token storage in localStorage with refresh logic

---

## Architecture

### Directory Structure

```
web-console/                      # Existing Preact + Vite app
├── src/
│   ├── pages/                    # Page components (React Router)
│   │   ├── auth/
│   │   │   ├── LoginPage.tsx
│   │   │   ├── SignupPage.tsx
│   │   │   └── DeviceFlowPage.tsx
│   │   ├── dashboard/
│   │   │   └── DashboardPage.tsx # User home
│   │   ├── org/
│   │   │   ├── OrgDashboard.tsx  # Org overview
│   │   │   ├── OrgSettings.tsx
│   │   │   ├── OrgMembers.tsx
│   │   │   ├── OrgBilling.tsx
│   │   │   └── OrgAgents.tsx
│   │   ├── project/
│   │   │   ├── BoardPage.tsx     # Kanban board
│   │   │   ├── RunsPage.tsx      # Run history
│   │   │   ├── BehaviorsPage.tsx
│   │   │   └── ProjectSettings.tsx
│   │   └── LandingPage.tsx
│   ├── components/
│   │   ├── ui/                   # shadcn/ui components (Preact-adapted)
│   │   │   ├── button.tsx
│   │   │   ├── card.tsx
│   │   │   ├── dialog.tsx
│   │   │   └── ...
│   │   ├── board/                # Board-specific components
│   │   │   ├── BoardColumn.tsx
│   │   │   ├── StoryCard.tsx
│   │   │   ├── TaskItem.tsx
│   │   │   └── DragDropContext.tsx
│   │   ├── agents/               # Agent-specific components
│   │   │   ├── AgentCard.tsx
│   │   │   ├── AgentStatusBadge.tsx
│   │   │   └── AgentAssignmentDialog.tsx
│   │   ├── runs/                 # Run monitoring components
│   │   │   ├── RunTimeline.tsx
│   │   │   ├── RunProgress.tsx
│   │   │   └── RunDetailPanel.tsx
│   │   └── shared/               # Shared components
│   │       ├── Avatar.tsx
│   │       ├── Navbar.tsx
│   │       └── Sidebar.tsx
│   ├── lib/
│   │   ├── api/                  # API client (TanStack Query)
│   │   │   ├── client.ts         # Axios instance
│   │   │   ├── queries/          # Query hooks
│   │   │   └── mutations/        # Mutation hooks
│   │   ├── auth/                 # Auth client
│   │   │   ├── AuthService.ts    # JWT token management
│   │   │   └── oauth.ts          # OAuth flow helpers
│   │   ├── websocket/            # WebSocket client
│   │   │   └── socket.ts
│   │   ├── stores/               # Zustand stores
│   │   │   ├── boardStore.ts
│   │   │   ├── agentStore.ts
│   │   │   └── authStore.ts
│   │   └── utils/                # Utility functions
│   │       ├── cn.ts             # Tailwind merge
│   │       └── format.ts
│   ├── hooks/                    # Custom Preact hooks
│   │   ├── useBoard.ts
│   │   ├── useAgent.ts
│   │   ├── useAuth.ts
│   │   └── useRealtime.ts
│   ├── types/                    # TypeScript types
│   │   ├── api.ts                # API response types
│   │   ├── board.ts
│   │   └── agent.ts
│   ├── router.tsx                # React Router setup
│   └── main.tsx                  # App entry point
├── public/
│   ├── images/
│   └── fonts/
├── index.html                    # Vite entry HTML
├── vite.config.ts               # Vite configuration
├── tailwind.config.js           # Tailwind configuration
└── tsconfig.json                # TypeScript configuration
```

### Data Flow

```
┌─────────────────────────────────────────────────────────┐
│                      User Browser                        │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  Preact + Vite SPA (Client-Side Rendering)               │
│                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │TanStack Query│  │   Zustand    │  │  Socket.IO   │  │
│  │ (Server Data)│  │(Client State)│  │  (Real-time) │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│         │                  │                  │          │
└─────────│──────────────────│──────────────────│─────────┘
          │                  │                  │
          ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────┐
│                   Backend Services                       │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   FastAPI    │  │   MCP Server │  │   WebSocket  │  │
│  │  REST API    │  │   (stdio)    │  │    Server    │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│         │                                      │          │
│         ▼                                      ▼          │
│  ┌─────────────────────────────────────────────────┐    │
│  │           PostgreSQL (Schema-per-Tenant)         │    │
│  └─────────────────────────────────────────────────┘    │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

---

## Page Layouts

### 1. Landing Page

**Route:** `/`

**Purpose:** Marketing site, feature showcase, pricing

**Key Sections:**
- Hero with CTA (Sign Up, See Demo)
- Features overview with animations
- Pricing comparison table
- Testimonials
- Footer with links

### 2. Authentication Pages

**Routes:** `/login`, `/signup`

**Design:** Centered card with logo, minimal distractions

**Features:**
- OAuth providers (GitHub, Google)
- Email/password fallback
- Magic link option
- Organization creation flow during signup

### 3. User Dashboard

**Route:** `/dashboard`

**Purpose:** User home showing all organizations and recent activity

**Layout:**
```
┌─────────────────────────────────────────────┐
│  Navbar (User menu, notifications)          │
├─────────────────────────────────────────────┤
│                                              │
│  Your Organizations                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│  │  Acme    │ │  Startup │ │  [+ New] │    │
│  │  Corp    │ │  Inc     │ │   Org    │    │
│  └──────────┘ └──────────┘ └──────────┘    │
│                                              │
│  Recent Activity                             │
│  • Task "API refactor" completed by Agent    │
│  • Story "User auth" moved to Done           │
│  • Sprint 23 started in Project Alpha        │
│                                              │
└─────────────────────────────────────────────┘
```

### 4. Organization Dashboard

**Route:** `/[org_slug]`

**Purpose:** Organization overview, project list, quick stats

**Layout:**
```
┌─────────────────────────────────────────────┐
│  Navbar                                      │
├───┬─────────────────────────────────────────┤
│   │                                          │
│ S │  Projects in Acme Corp                   │
│ I │  ┌──────────────┐ ┌──────────────┐      │
│ D │  │ Project      │ │ Project      │      │
│ E │  │ Alpha        │ │ Beta         │      │
│ B │  │              │ │              │      │
│ A │  │ 12 stories   │ │ 8 stories    │      │
│ R │  │ 3 agents     │ │ 2 agents     │      │
│   │  └──────────────┘ └──────────────┘      │
│ • │                                          │
│ P │  Organization Stats                      │
│ r │  ┌────────┐ ┌────────┐ ┌────────┐       │
│ o │  │ 45K    │ │ 23     │ │ 8      │       │
│ j │  │ tokens │ │ runs   │ │ agents │       │
│ e │  │ used   │ │ today  │ │ active │       │
│ c │  └────────┘ └────────┘ └────────┘       │
│ t │                                          │
│ s │                                          │
│   │                                          │
│ • │                                          │
│ M │                                          │
│ e │                                          │
│ m │                                          │
│ b │                                          │
│ e │                                          │
│ r │                                          │
│ s │                                          │
│   │                                          │
│ • │                                          │
│ A │                                          │
│ g │                                          │
│ e │                                          │
│ n │                                          │
│ t │                                          │
│ s │                                          │
└───┴─────────────────────────────────────────┘
```

### 5. Kanban Board (Core Feature)

**Route:** `/[org_slug]/[project_slug]/board`

**Purpose:** Main workspace for agile development

**Layout:**
```
┌─────────────────────────────────────────────────────────┐
│  Navbar                                                  │
├───┬─────────────────────────────────────────────────────┤
│   │ Board: Main     Sprint 23 ▼   [+ Create Story]      │
│   ├─────────────────────────────────────────────────────┤
│ S │ Filters: [All Agents ▼] [All Labels ▼] [Search...]  │
│ I ├──────┬──────────┬──────────┬──────────┬────────────┤
│ D │ Back │ To Do    │ In Prog  │ Review   │ Done       │
│ E │ log  │ (3/5)    │ (2/3)    │ (1/∞)    │            │
│ B ├──────┼──────────┼──────────┼──────────┼────────────┤
│ A │      │┌────────┐│┌────────┐│┌────────┐│┌──────────┐│
│ R ││Story││ Story  │││ Story  │││ Story  │││ Story    ││
│   ││  #1 ││   #2   │││   #3   │││   #4   │││   #5     ││
│   ││     ││        │││        │││        │││          ││
│ • ││ 🤖  ││  👤    │││  🤖    │││  👤    │││ ✓        ││
│ P ││Agent││ John   │││ Agent  │││ Sarah  │││ Agent    ││
│ r ││Bot  ││        │││ Bot    │││        │││ Bot      ││
│ o ││     ││        │││        │││        │││          ││
│ j ││ 5SP ││  3SP   │││  8SP   │││  5SP   │││  3SP     ││
│ e │└─────┘│└────────┘│└────────┘│└────────┘│└──────────┘│
│ c │      │          │          │          │            │
│ t │      │          │┌────────┐│          │            │
│   │      │          ││ Story  ││          │            │
│   │      │          ││   #6   ││          │            │
│   │      │          │└────────┘│          │            │
└───┴──────┴──────────┴──────────┴──────────┴────────────┘

[Agent Activity Panel - Bottom Drawer]
🤖 AgentBot: Running task "API refactor" ████████░░ 80%
🤖 ReviewBot: Idle - Available for assignment
```

**Key Features:**
- Drag-and-drop between columns
- Real-time updates (other users' changes visible instantly)
- Agent status indicators (active, idle, busy)
- WIP limits displayed (e.g., "In Progress (2/3)")
- Quick assign agents via drag-and-drop
- Filter by assignee, labels, sprint
- Expandable story cards showing tasks

### 6. Story Detail Modal

**Trigger:** Click on story card

**Layout:**
```
┌─────────────────────────────────────────────────────┐
│  Story #234: Implement user authentication       [X]│
├─────────────────────────────────────────────────────┤
│                                                      │
│  Epic: [User Management ▼]  Sprint: [Sprint 23 ▼]  │
│  Assignee: [🤖 AgentBot ▼]   Priority: [High ▼]    │
│  Story Points: [5 ▼]         Labels: [+]            │
│                                                      │
│  Description                                         │
│  ┌────────────────────────────────────────────────┐ │
│  │ As a user, I want to log in with OAuth...     │ │
│  └────────────────────────────────────────────────┘ │
│                                                      │
│  Acceptance Criteria                                 │
│  ☐ Google OAuth integration                          │
│  ☐ GitHub OAuth integration                          │
│  ☐ Session management                                │
│                                                      │
│  Tasks (3)                                           │
│  ☑ Setup OAuth providers - AgentBot (2h)             │
│  ☐ Implement session store - Unassigned (3h)         │
│  ☐ Add logout flow - Unassigned (1h)                 │
│                                                      │
│  [+ Add Task]                                        │
│                                                      │
│  Activity                                            │
│  👤 Sarah moved to "In Progress" - 2 min ago         │
│  🤖 AgentBot completed task "Setup OAuth" - 1h ago   │
│  👤 John assigned AgentBot - 3h ago                  │
│                                                      │
│  ┌────────────────────────────────────────────────┐ │
│  │ Add comment...                                 │ │
│  └────────────────────────────────────────────────┘ │
│                                                      │
│              [Delete Story]     [Save Changes]       │
└─────────────────────────────────────────────────────┘
```

### 7. Agent Management

**Route:** `/agents` (registry) and `/[org_slug]/agents` (org-scoped view)

**Purpose:** Create, configure, and monitor agents

**Layout:**
```
┌─────────────────────────────────────────────────────┐
│  Navbar                                              │
├───┬─────────────────────────────────────────────────┤
│   │ Agents                       [+ Create Agent]   │
│   ├─────────────────────────────────────────────────┤
│ S │                                                  │
│ I │ ┌───────────────────────────────────────────┐   │
│ D │ │ 🤖 CodeBot            [Active ●]  [Edit]  │   │
│ E │ │ Type: Coder                                │   │
│ B │ │ Model: gpt-4o-mini                         │   │
│ A │ │                                            │   │
│ R │ │ Stats:                                     │   │
│   │ │ • 23 tasks completed                       │   │
│   │ │ • 45K tokens used                          │   │
│ • │ │ • 2.5h avg task time                       │   │
│ O │ │                                            │   │
│ r │ │ Current Assignment:                        │   │
│ g │ │ Task "API refactor" - 80% complete         │   │
│   │ │ ████████░░                                 │   │
│   │ └───────────────────────────────────────────┘   │
│   │                                                  │
│   │ ┌───────────────────────────────────────────┐   │
│   │ │ 🤖 ReviewBot          [Idle ○]    [Edit]  │   │
│   │ │ Type: Reviewer                             │   │
│   │ │ Model: claude-3-5-sonnet                   │   │
│   │ │                                            │   │
│   │ │ Stats:                                     │   │
│   │ │ • 15 tasks completed                       │   │
│   │ │ • 32K tokens used                          │   │
│   │ │ • 1.8h avg task time                       │   │
│   │ │                                            │   │
│   │ │ Available for assignment                   │   │
│   │ └───────────────────────────────────────────┘   │
└───┴─────────────────────────────────────────────────┘
```

### 8. Run Monitoring

**Route:** `/[org_slug]/[project_slug]/runs`

**Purpose:** Monitor agent executions with real-time progress

**Layout:**
```
┌─────────────────────────────────────────────────────┐
│  Navbar                                              │
├───┬─────────────────────────────────────────────────┤
│   │ Runs                    [Status: All ▼] [🔄]    │
│   ├─────────────────────────────────────────────────┤
│ S │                                                  │
│ I │ ┌───────────────────────────────────────────┐   │
│ D │ │ Run #1234                    [Running ●]  │   │
│ E │ │ Task: "API refactor"                      │   │
│ B │ │ Agent: CodeBot                            │   │
│ A │ │ Started: 5 min ago                        │   │
│ R │ │                                            │   │
│   │ │ Progress: 80%                              │   │
│   │ │ ████████████████░░░░                       │   │
│ • │ │                                            │   │
│ P │ │ Current Step:                              │   │
│ r │ │ "Generating unit tests..."                 │   │
│ o │ │                                            │   │
│ j │ │ Tokens: 12,340 / 50,000                    │   │
│ e │ └───────────────────────────────────────────┘   │
│ c │                                                  │
│ t │ ┌───────────────────────────────────────────┐   │
│   │ │ Run #1233                    [Success ✓]  │   │
│   │ │ Task: "Setup OAuth"                       │   │
│   │ │ Agent: CodeBot                            │   │
│   │ │ Completed: 1 hour ago                     │   │
│   │ │ Duration: 8m 23s                          │   │
│   │ │ Tokens: 8,421                             │   │
│   │ └───────────────────────────────────────────┘   │
│   │                                                  │
│   │ ┌───────────────────────────────────────────┐   │
│   │ │ Run #1232                    [Failed ✗]   │   │
│   │ │ Task: "Database migration"                │   │
│   │ │ Agent: CodeBot                            │   │
│   │ │ Failed: 2 hours ago                       │   │
│   │ │ Error: Exceeded token budget              │   │
│   │ └───────────────────────────────────────────┘   │
└───┴─────────────────────────────────────────────────┘
```

### 9. Billing Dashboard

**Route:** `/[org_slug]/billing`

**Purpose:** Subscription management, usage tracking, invoices

**Layout:**
```
┌─────────────────────────────────────────────────────┐
│  Navbar                                              │
├───┬─────────────────────────────────────────────────┤
│   │ Billing & Usage                                 │
│   ├─────────────────────────────────────────────────┤
│ S │                                                  │
│ I │ Current Plan: Team ($99/month)                   │
│ D │ Next billing: Dec 31, 2025                       │
│ E │                                        [Upgrade] │
│ B │                                                  │
│ A │ Usage This Period                                │
│ R │ ┌────────────────────────────────────────────┐  │
│   │ │ Tokens                                     │  │
│   │ │ 1.2M / 2M used ████████████░░░░  60%      │  │
│ • │ │                                            │  │
│ O │ │ Runs                                       │  │
│ r │ │ 234 / ∞                                    │  │
│ g │ │                                            │  │
│   │ │ Storage                                    │  │
│   │ │ 4.2 GB / 100 GB used ██░░░░░░░░░  4%      │  │
│   │ └────────────────────────────────────────────┘  │
│   │                                                  │
│   │ Payment Method                                   │
│   │ ┌────────────────────────────────────────────┐  │
│   │ │ Visa •••• 4242                             │  │
│   │ │ Expires 12/2026              [Update]      │  │
│   │ └────────────────────────────────────────────┘  │
│   │                                                  │
│   │ Invoices                                         │
│   │ ┌────────────────────────────────────────────┐  │
│   │ │ Nov 2025    $99.00    Paid     [Download]  │  │
│   │ │ Oct 2025    $99.00    Paid     [Download]  │  │
│   │ │ Sep 2025    $99.00    Paid     [Download]  │  │
│   │ └────────────────────────────────────────────┘  │
└───┴─────────────────────────────────────────────────┘
```

---

## Component Library

### Core UI Components (shadcn/ui)

All components copied from shadcn/ui and customized:

```typescript
// components/ui/button.tsx
import { h } from "preact"
import { cn } from "@/lib/utils"
import type { JSX } from "preact"

interface ButtonProps extends JSX.HTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "destructive" | "outline" | "ghost" | "link"
  size?: "default" | "sm" | "lg" | "icon"
}

export function Button({ className, variant = "default", size = "default", ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-md font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2",
        "disabled:pointer-events-none disabled:opacity-50",
        {
          "bg-primary text-primary-foreground hover:bg-primary/90": variant === "default",
          "bg-destructive text-destructive-foreground hover:bg-destructive/90": variant === "destructive",
          "border border-input hover:bg-accent hover:text-accent-foreground": variant === "outline",
          "hover:bg-accent hover:text-accent-foreground": variant === "ghost",
        },
        {
          "h-10 px-4 py-2": size === "default",
          "h-9 px-3 text-sm": size === "sm",
          "h-11 px-8": size === "lg",
          "h-10 w-10": size === "icon",
        },
        className
      )}
      {...props}
    />
  )
}
```

### Board Components

```typescript
// components/board/StoryCard.tsx
import { h } from "preact"
import { useSortable } from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { Card } from "@/components/ui/card"
import { Avatar } from "@/components/shared/Avatar"
import { Badge } from "@/components/ui/badge"
import type { Story } from "@/types/board"

interface StoryCardProps {
  story: Story
  onClick: () => void
}

export function StoryCard({ story, onClick }: StoryCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: story.story_id,
  })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  return (
    <Card
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      onClick={onClick}
      className="p-4 cursor-pointer hover:shadow-md transition-shadow"
    >
      <div className="flex items-start justify-between mb-2">
        <h4 className="font-medium text-sm">{story.title}</h4>
        {story.story_points && (
          <Badge variant="secondary">{story.story_points}SP</Badge>
        )}
      </div>

      {story.labels.length > 0 && (
        <div className="flex gap-1 mb-2">
          {story.labels.map((label) => (
            <Badge key={label} variant="outline" className="text-xs">
              {label}
            </Badge>
          ))}
        </div>
      )}

      {story.assignee_id && (
        <div className="flex items-center gap-2 mt-2">
          {story.assignee_type === "agent" ? (
            <>
              <span className="text-xl">🤖</span>
              <span className="text-xs text-muted-foreground">{story.assignee_name}</span>
            </>
          ) : (
            <>
              <Avatar size="sm" src={story.assignee_avatar} name={story.assignee_name} />
              <span className="text-xs text-muted-foreground">{story.assignee_name}</span>
            </>
          )}
        </div>
      )}
    </Card>
  )
}
```

### Agent Components

```typescript
// components/agents/AgentCard.tsx
import { h } from "preact"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import type { Agent } from "@/types/agent"

interface AgentCardProps {
  agent: Agent
  onEdit: () => void
}

export function AgentCard({ agent, onEdit }: AgentCardProps) {
  const statusColor = {
    active: "success",
    busy: "warning",
    paused: "default",
    disabled: "destructive",
  }[agent.status]

  return (
    <Card className="p-6">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <span className="text-3xl">🤖</span>
          <div>
            <h3 className="font-semibold text-lg">{agent.name}</h3>
            <p className="text-sm text-muted-foreground">{agent.agent_type}</p>
          </div>
        </div>
        <Badge variant={statusColor}>{agent.status}</Badge>
      </div>

      <div className="space-y-2 mb-4">
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">Model:</span>
          <span className="font-medium">{agent.llm_model}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">Tasks Completed:</span>
          <span className="font-medium">{agent.total_tasks_completed}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">Tokens Used:</span>
          <span className="font-medium">{agent.total_tokens_used.toLocaleString()}</span>
        </div>
      </div>

      {agent.current_task && (
        <div className="mb-4">
          <p className="text-sm font-medium mb-2">Current Task:</p>
          <p className="text-sm text-muted-foreground mb-2">{agent.current_task.title}</p>
          <Progress value={agent.current_task.progress} />
        </div>
      )}

      <button onClick={onEdit} className="w-full text-sm text-primary hover:underline">
        Edit Configuration
      </button>
    </Card>
  )
}
```

---

## State Management

### Zustand Stores

```typescript
// lib/stores/authStore.ts
import { create } from "zustand"
import { persist } from "zustand/middleware"

interface AuthState {
  accessToken: string | null
  refreshToken: string | null
  user: User | null

  setTokens: (accessToken: string, refreshToken: string) => void
  setUser: (user: User) => void
  logout: () => void
  refreshToken: () => Promise<boolean>
}

export const authStore = create<AuthState>()(persist(
  (set, get) => ({
    accessToken: null,
    refreshToken: null,
    user: null,

    setTokens: (accessToken, refreshToken) => set({ accessToken, refreshToken }),

    setUser: (user) => set({ user }),

    logout: () => {
      set({ accessToken: null, refreshToken: null, user: null })
      localStorage.removeItem("auth-storage")
    },

    refreshToken: async () => {
      const { refreshToken } = get()
      if (!refreshToken) return false

      try {
        const response = await fetch(`${import.meta.env.VITE_API_URL}/v1/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        })

        if (response.ok) {
          const { access_token, refresh_token } = await response.json()
          set({ accessToken: access_token, refreshToken: refresh_token })
          return true
        }
        return false
      } catch (error) {
        return false
      }
    },
  }),
  {
    name: "auth-storage",
    partialize: (state) => ({
      accessToken: state.accessToken,
      refreshToken: state.refreshToken,
      user: state.user,
    }),
  }
))

// lib/stores/boardStore.ts
import { create } from "zustand"
import type { Board, Story, BoardColumn } from "@/types/board"

interface BoardStore {
  board: Board | null
  columns: BoardColumn[]
  stories: Record<string, Story[]>  // columnId -> stories

  setBoard: (board: Board) => void
  setColumns: (columns: BoardColumn[]) => void
  setStories: (stories: Story[]) => void
  moveStory: (storyId: string, fromColumnId: string, toColumnId: string) => void
  updateStory: (story: Story) => void

  // Real-time updates
  handleStoryMoved: (event: StoryMovedEvent) => void
  handleStoryUpdated: (event: StoryUpdatedEvent) => void
}

export const useBoardStore = create<BoardStore>((set, get) => ({
  board: null,
  columns: [],
  stories: {},

  setBoard: (board) => set({ board }),

  setColumns: (columns) => set({ columns }),

  setStories: (stories) => {
    const storiesByColumn: Record<string, Story[]> = {}
    stories.forEach((story) => {
      if (!storiesByColumn[story.column_id]) {
        storiesByColumn[story.column_id] = []
      }
      storiesByColumn[story.column_id].push(story)
    })
    set({ stories: storiesByColumn })
  },

  moveStory: (storyId, fromColumnId, toColumnId) => {
    const { stories } = get()
    const fromStories = stories[fromColumnId] || []
    const toStories = stories[toColumnId] || []

    const story = fromStories.find((s) => s.story_id === storyId)
    if (!story) return

    set({
      stories: {
        ...stories,
        [fromColumnId]: fromStories.filter((s) => s.story_id !== storyId),
        [toColumnId]: [...toStories, { ...story, column_id: toColumnId }],
      },
    })
  },

  handleStoryMoved: (event) => {
    get().moveStory(event.story_id, event.from_column, event.to_column)
  },

  handleStoryUpdated: (event) => {
    // Update story in place
    const { stories } = get()
    const columnStories = stories[event.story.column_id] || []
    const updatedStories = columnStories.map((s) =>
      s.story_id === event.story.story_id ? event.story : s
    )

    set({
      stories: {
        ...stories,
        [event.story.column_id]: updatedStories,
      },
    })
  },
}))
```

### React Query Setup

```typescript
// lib/api/client.ts
import axios from "axios"
import { authStore } from "@/lib/stores/authStore"

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:8000",
  headers: {
    "Content-Type": "application/json",
  },
})

// Add auth token to requests
apiClient.interceptors.request.use(async (config) => {
  const token = authStore.getState().accessToken
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }

  // Add org context from URL
  const orgSlug = window.location.pathname.split("/")[1]
  if (orgSlug && orgSlug !== "login" && orgSlug !== "signup") {
    config.headers["X-Organization-Slug"] = orgSlug
  }

  return config
})

// Handle token refresh on 401
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      // Attempt token refresh
      const refreshed = await authStore.getState().refreshToken()
      if (refreshed) {
        // Retry original request
        return apiClient.request(error.config)
      } else {
        // Redirect to login
        authStore.getState().logout()
        window.location.href = "/login"
      }
    }
    return Promise.reject(error)
  }
)

// lib/api/queries/board.ts
import { useQuery } from "@tanstack/react-query"
import { apiClient } from "../client"
import type { Board, Story } from "@/types/board"

export function useBoard(boardId: string) {
  return useQuery({
    queryKey: ["board", boardId],
    queryFn: async () => {
      const { data } = await apiClient.get<Board>(`/v1/boards/${boardId}`)
      return data
    },
  })
}

export function useStories(boardId: string) {
  return useQuery({
    queryKey: ["stories", boardId],
    queryFn: async () => {
      const { data } = await apiClient.get<Story[]>(`/v1/boards/${boardId}/stories`)
      return data
    },
  })
}

// lib/api/mutations/board.ts
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { apiClient } from "../client"

export function useMoveStory() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ storyId, columnId }: { storyId: string; columnId: string }) => {
      const { data } = await apiClient.post(`/v1/stories/${storyId}/move`, { column_id: columnId })
      return data
    },
    onSuccess: (_, { storyId }) => {
      // Invalidate relevant queries
      queryClient.invalidateQueries({ queryKey: ["stories"] })
    },
    // Optimistic update
    onMutate: async ({ storyId, columnId }) => {
      await queryClient.cancelQueries({ queryKey: ["stories"] })

      const previousStories = queryClient.getQueryData(["stories"])

      // Update cache optimistically
      queryClient.setQueryData(["stories"], (old: Story[]) =>
        old.map((story) =>
          story.story_id === storyId ? { ...story, column_id: columnId } : story
        )
      )

      return { previousStories }
    },
    onError: (err, variables, context) => {
      // Rollback on error
      if (context?.previousStories) {
        queryClient.setQueryData(["stories"], context.previousStories)
      }
    },
  })
}
```

---

## Real-Time Features

### WebSocket Integration

```typescript
// lib/websocket/socket.ts
import { io, Socket } from "socket.io-client"
import { authStore } from "@/lib/stores/authStore"

class WebSocketClient {
  private socket: Socket | null = null
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5

  connect(channel: string) {
    const token = authStore.getState().accessToken

    this.socket = io(import.meta.env.VITE_WS_URL || "ws://localhost:8000", {
      auth: {
        token,
      },
      transports: ["websocket"],
    })

    this.socket.emit("join", { channel })

    this.socket.on("connect", () => {
      console.log(`Connected to channel: ${channel}`)
      this.reconnectAttempts = 0
    })

    this.socket.on("disconnect", () => {
      console.log("Disconnected from WebSocket")
      this.handleReconnect(channel)
    })

    this.socket.on("error", (error) => {
      console.error("WebSocket error:", error)
    })

    return this.socket
  }

  private handleReconnect(channel: string) {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++
      setTimeout(() => {
        this.connect(channel)
      }, Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000))
    }
  }

  disconnect() {
    if (this.socket) {
      this.socket.disconnect()
      this.socket = null
    }
  }

  on(event: string, handler: (data: any) => void) {
    this.socket?.on(event, handler)
  }

  off(event: string, handler?: (data: any) => void) {
    this.socket?.off(event, handler)
  }

  emit(event: string, data: any) {
    this.socket?.emit(event, data)
  }
}

export const wsClient = new WebSocketClient()

// Custom hook for board real-time updates
export function useBoardRealtimeSync(boardId: string) {
  const boardStore = useBoardStore()

  useEffect(() => {
    wsClient.connect(`board:${boardId}`)

    const handleStoryMoved = (event: StoryMovedEvent) => {
      boardStore.handleStoryMoved(event)
    }

    const handleStoryUpdated = (event: StoryUpdatedEvent) => {
      boardStore.handleStoryUpdated(event)
    }

    const handleAgentProgress = (event: AgentProgressEvent) => {
      // Update agent progress in UI
      toast.info(`${event.agent_name}: ${event.status}`)
    }

    wsClient.on("story_moved", handleStoryMoved)
    wsClient.on("story_updated", handleStoryUpdated)
    wsClient.on("agent_progress", handleAgentProgress)

    return () => {
      wsClient.off("story_moved", handleStoryMoved)
      wsClient.off("story_updated", handleStoryUpdated)
      wsClient.off("agent_progress", handleAgentProgress)
      wsClient.disconnect()
    }
  }, [boardId])
}
```

### Server-Sent Events for Run Progress

```typescript
// lib/api/sse.ts
export function subscribeToRunProgress(runId: string, onProgress: (event: RunProgressEvent) => void) {
  const eventSource = new EventSource(
    `${import.meta.env.VITE_API_URL}/v1/runs/${runId}/stream`
  )

  eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data)
    onProgress(data)
  }

  eventSource.onerror = (error) => {
    console.error("SSE error:", error)
    eventSource.close()
  }

  return () => {
    eventSource.close()
  }
}

// Usage in component
function RunProgressPanel({ runId }: { runId: string }) {
  const [progress, setProgress] = useState(0)
  const [currentStep, setCurrentStep] = useState("")

  useEffect(() => {
    const unsubscribe = subscribeToRunProgress(runId, (event) => {
      setProgress(event.progress)
      setCurrentStep(event.current_step)
    })

    return unsubscribe
  }, [runId])

  return (
    <div>
      <p>{currentStep}</p>
      <Progress value={progress} />
    </div>
  )
}
```

---

## Responsive Design

### Breakpoints (Tailwind)

```javascript
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      screens: {
        'xs': '475px',
        'sm': '640px',
        'md': '768px',
        'lg': '1024px',
        'xl': '1280px',
        '2xl': '1536px',
      },
    },
  },
}
```

### Mobile Adaptations

**Board View on Mobile:**
- Horizontal scroll for columns
- Tap to expand story cards
- Bottom sheet for story details
- Floating action button for "+ Create Story"

**Sidebar on Mobile:**
- Collapsed by default
- Hamburger menu to toggle
- Overlay when open

```typescript
// Mobile-responsive board layout
<div className="flex flex-col lg:flex-row h-screen">
  {/* Sidebar - hidden on mobile by default */}
  <aside className={cn(
    "w-64 bg-gray-50 border-r",
    "absolute lg:relative inset-y-0 left-0 z-40",
    "transform transition-transform lg:translate-x-0",
    isSidebarOpen ? "translate-x-0" : "-translate-x-full"
  )}>
    {/* Sidebar content */}
  </aside>

  {/* Main content */}
  <main className="flex-1 overflow-auto">
    {/* Board columns - horizontal scroll on mobile */}
    <div className="flex gap-4 p-4 overflow-x-auto">
      {columns.map((column) => (
        <BoardColumn key={column.column_id} column={column} />
      ))}
    </div>
  </main>
</div>
```

---

## Accessibility

### WCAG AA Compliance Checklist

- [ ] **Color Contrast** - 4.5:1 minimum for text, 3:1 for large text
- [ ] **Keyboard Navigation** - All interactive elements accessible via Tab
- [ ] **Focus Indicators** - Visible focus rings on all focusable elements
- [ ] **Screen Reader Support** - ARIA labels, roles, and live regions
- [ ] **Alt Text** - All images have descriptive alt text
- [ ] **Form Labels** - All inputs have associated labels
- [ ] **Skip Links** - "Skip to main content" link
- [ ] **Semantic HTML** - Proper heading hierarchy, landmarks

### Implementation

```tsx
// Accessible button with ARIA
<button
  aria-label="Create new story"
  aria-pressed={isCreating}
  onClick={handleCreate}
  className="..."
>
  <PlusIcon className="w-4 h-4" aria-hidden="true" />
  <span>Create Story</span>
</button>

// Accessible modal
<Dialog open={isOpen} onOpenChange={setIsOpen}>
  <DialogTrigger asChild>
    <Button>Open Settings</Button>
  </DialogTrigger>
  <DialogContent aria-describedby="dialog-description">
    <DialogHeader>
      <DialogTitle>Settings</DialogTitle>
      <DialogDescription id="dialog-description">
        Manage your project settings and preferences.
      </DialogDescription>
    </DialogHeader>
    {/* Modal content */}
  </DialogContent>
</Dialog>

// Live region for real-time updates
<div
  role="status"
  aria-live="polite"
  aria-atomic="true"
  className="sr-only"
>
  {latestUpdate && `Story moved: ${latestUpdate.title}`}
</div>
```

---

## Performance Optimization

### Next.js Optimizations

1. **Server Components by Default** - Fetch data on server, reduce client JS
2. **Dynamic Imports** - Code split heavy components
3. **Image Optimization** - Use `next/image` with automatic WebP
4. **Font Optimization** - Use `next/font` for self-hosted fonts
5. **Route Prefetching** - Automatic prefetching of visible links

### React Query Caching

```typescript
// Aggressive caching for static data
export function useOrganization(orgId: string) {
  return useQuery({
    queryKey: ["organization", orgId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/v1/orgs/${orgId}`)
      return data
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
    cacheTime: 30 * 60 * 1000, // 30 minutes
  })
}

// Real-time refetching for dynamic data
export function useActiveAgents(orgId: string) {
  return useQuery({
    queryKey: ["agents", orgId, "active"],
    queryFn: async () => {
      const { data } = await apiClient.get(`/v1/orgs/${orgId}/agents`, {
        params: { status: "active,busy" },
      })
      return data
    },
    refetchInterval: 10_000, // Refetch every 10 seconds
  })
}
```

### Bundle Size Monitoring

```bash
# Analyze bundle
npm run build
npm run analyze

# Expected bundle sizes:
# - First Load JS: < 200 KB
# - Route chunks: < 50 KB each
```

---

## Development Workflow

### Local Setup

```bash
# Navigate to existing web-console
cd web-console

# Install dependencies (if not already installed)
npm install

# Install new dependencies for multi-tenant features
npm install @tanstack/react-query zustand socket.io-client @dnd-kit/core @dnd-kit/sortable

# Set up environment
cp .env.example .env.local
# Edit .env.local with API URLs, Stripe keys, etc.

# Run development server
npm run dev
# Open http://localhost:5173 (Vite default)
```

### Environment Variables

```bash
# .env.local (Vite uses VITE_ prefix)
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
VITE_MCP_SERVER_URL=http://localhost:8001

# OAuth Providers (client IDs only - secrets stay on backend)
VITE_GITHUB_CLIENT_ID=your-github-client-id
VITE_GOOGLE_CLIENT_ID=your-google-client-id

# Stripe (publishable key only)
VITE_STRIPE_PUBLISHABLE_KEY=pk_test_...
```

### Vite Configuration

```typescript
// vite.config.ts
import { defineConfig } from "vite"
import preact from "@preact/preset-vite"
import path from "path"

export default defineConfig({
  plugins: [preact()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "react": "preact/compat",
      "react-dom": "preact/compat",
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, "/v1"),
      },
    },
  },
  build: {
    target: "esnext",
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["preact", "preact/hooks"],
          router: ["wouter"],
          query: ["@tanstack/react-query"],
          ui: ["@dnd-kit/core", "@dnd-kit/sortable"],
        },
      },
    },
  },
})
```

### Testing

```bash
# Unit tests (Jest + React Testing Library)
npm run test

# E2E tests (Playwright)
npm run test:e2e

# Component tests (Storybook)
npm run storybook
```

### Deployment

```bash
# Build for production
npm run build
# Output: dist/ folder with static assets

# Preview production build
npm run preview

# Deploy to static hosting (Vercel, Netlify, Cloudflare Pages, etc.)
# Example: Vercel
vercel deploy --prod

# Or serve with nginx
docker build -t amprealize-web .
docker run -p 8080:80 amprealize-web
```

### Dockerfile (Nginx Static Hosting)

```dockerfile
# Dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### Nginx Configuration

```nginx
# nginx.conf
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # SPA routing - fallback to index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Cache static assets
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Gzip compression
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
}
```

---

## Related Documents

- [`MULTI_TENANT_ARCHITECTURE.md`](./MULTI_TENANT_ARCHITECTURE.md) - Backend multi-tenancy design
- [`WORK_STRUCTURE.md`](../WORK_STRUCTURE.md) - Epic 13 tracking
- [`MCP_SERVER_DESIGN.md`](contracts/MCP_SERVER_DESIGN.md) - MCP integration patterns

---

*Document created: 2025-12-02*
*Behaviors referenced: `behavior_design_api_contract`, `behavior_validate_accessibility`, `behavior_craft_messaging`*
