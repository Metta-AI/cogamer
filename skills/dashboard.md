---
name: dashboard
description: Generate a self-contained HTML dashboard from cogamer state. Shows KPIs, experiment history, and current priorities.
---

# Dashboard

Generate a self-contained HTML dashboard from cogamer state.

## Steps

1. **Read cogamer state**:
   - `~/repo/cogamer/todos.md` — current priorities and dead ends
   - `~/repo/memory/learnings.md` — recent insights
   - `~/repo/memory/sessions/` — session logs
   - `~/repo/memory/summaries/` — periodic rollups

2. **Include domain dashboard** — If `~/repo/cogamer/dashboard.md` exists, read it and follow those instructions to gather domain-specific data and dashboard sections.

3. **Generate HTML** at `~/repo/cogamer/dashboard/index.html`:
   - **Status banner** (top of page): Add a `<div id="heartbeat-banner">` that auto-updates by fetching `/heartbeat.json` every 10 seconds. Do NOT bake heartbeat data into the HTML — always fetch it live. Include this script:
     ```html
     <script>
     function updateHeartbeat(){
       fetch('/heartbeat.json').then(r=>r.json()).then(hb=>{
         const el=document.getElementById('heartbeat-banner');
         const ts=hb.timestamp?new Date(hb.timestamp):null;
         const ago=ts?Math.floor((Date.now()-ts)/60000):null;
         const rel=ago===null?'':ago<1?'just now':ago<60?ago+'m ago':Math.floor(ago/60)+'h ago';
         const time=ts?ts.toISOString().replace('T',' ').replace(/\.\d+Z/,' UTC')+' ['+rel+']':'';
         el.textContent=(hb.status||'unknown').toUpperCase()+': '+(hb.message||'')+'  '+time;
         el.className='heartbeat-banner status-'+(hb.status||'unknown');
       }).catch(()=>{});
     }
     updateHeartbeat();setInterval(updateHeartbeat,10000);
     </script>
     ```
     Style the banner color based on status class: green for "idle"/"active"/"working", yellow for "sleeping", red for "stopping".
   - **Active TODOs**: current priorities
   - **Recent Conversations**: read `~/repo/memory/conversation.jsonl` (each line is JSON with `timestamp`, `direction`, `channel_id`, `sender`, `body`). Show the last 20 messages grouped by channel, with incoming messages on the left and outgoing replies on the right, styled as a chat view.
   - **Session timeline**: recent sessions with change, result, notes
   - **Learnings**: actionable insights not yet folded into docs
   - **Summary**: latest weekly summary if available
   - Domain-specific sections from step 2
   - Include a footer with generation timestamp and a **Regenerate** button. The button should POST to `/regenerate` on the same origin (no auth needed) and show "Regenerating..." while waiting, then reload the page after 30 seconds:
     ```html
     <button onclick="fetch('/regenerate',{method:'POST'}).then(()=>{this.textContent='Regenerating...';setTimeout(()=>location.reload(),30000)})">Regenerate</button>
     ```

The dashboard is served live via a local webserver + Cloudflare tunnel. No need to commit or push — just write the file and it's immediately visible.

## Design

Catppuccin Mocha palette (dark-first). Chart.js for graphs if needed. Responsive grid. Self-contained single HTML file.

## Important

- The **Recent Conversations** section is critical — always include it even if `conversation.jsonl` is empty (show "No conversations yet").
- Read conversation.jsonl line by line (each line is independent JSON). If the file doesn't exist, that's fine — just show the empty state.
