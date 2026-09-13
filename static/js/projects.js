import Storage from './storage.js';

const API_BASE = window.location.origin;
const TABS = [
  'overview',
  'conversations',
  'agents',
  'tasks',
  'files',
  'memory',
  'models',
  'settings',
];

let pane = null;
let projects = [];
let currentProject = null;
let currentTab = 'overview';
let dependencies = {};

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: 'same-origin',
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === 'string') detail = payload.detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function ensurePane() {
  if (pane) return pane;
  pane = element('section', 'project-pane');
  pane.id = 'project-pane';
  pane.hidden = true;
  pane.setAttribute('role', 'dialog');
  pane.setAttribute('aria-modal', 'true');
  pane.setAttribute('aria-label', 'Projects');
  pane.innerHTML = `
    <header class="project-pane-header">
      <div class="project-pane-title" id="project-pane-title">Projects</div>
      <button type="button" class="project-pane-close" id="project-pane-close" aria-label="Close project workspace">×</button>
    </header>
    <div class="project-pane-body">
      <aside class="project-list" aria-label="Project list">
        <form class="project-create-form" id="project-create-form">
          <input id="project-create-name" maxlength="120" placeholder="New project name" aria-label="New project name" required>
          <button class="project-action primary" type="submit">Create</button>
        </form>
        <div id="project-list-items" class="project-list-items" aria-live="polite"></div>
      </aside>
      <main class="project-workspace" id="project-workspace">
        <nav class="project-tabs" role="tablist" aria-label="Project sections">
          ${TABS.map((tab) => `<button type="button" class="project-tab" id="project-tab-${tab}" role="tab" data-project-tab="${tab}" aria-controls="project-panel-${tab}" aria-selected="${tab === 'overview'}">${tab[0].toUpperCase()}${tab.slice(1)}</button>`).join('')}
        </nav>
        ${TABS.map((tab) => `<section class="project-panel" id="project-panel-${tab}" role="tabpanel" aria-labelledby="project-tab-${tab}" ${tab === 'overview' ? '' : 'hidden'}></section>`).join('')}
      </main>
    </div>`;
  document.body.appendChild(pane);
  pane.querySelector('#project-pane-close').addEventListener('click', closeProjects);
  pane.querySelector('#project-create-form').addEventListener('submit', createProject);
  pane.querySelectorAll('[data-project-tab]').forEach((button) => {
    button.addEventListener('click', () => activateTab(button.dataset.projectTab));
  });
  pane.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeProjects();
  });
  return pane;
}

function showError(message) {
  if (dependencies.uiModule?.showError) dependencies.uiModule.showError(message);
  else console.error(message);
}

function showToast(message) {
  if (dependencies.uiModule?.showToast) dependencies.uiModule.showToast(message);
}

function renderProjectList() {
  const container = pane.querySelector('#project-list-items');
  container.replaceChildren();
  if (!projects.length) {
    container.appendChild(element('div', 'project-empty', 'Create a project to group conversations and files.'));
    return;
  }
  projects.forEach((project) => {
    const button = element('button', 'project-list-item');
    button.type = 'button';
    button.dataset.projectId = project.id;
    button.classList.toggle('active', currentProject?.id === project.id);
    const name = element('div', '', project.name);
    const meta = element(
      'div',
      'project-list-meta',
      `${project.session_count || 0} conversation${project.session_count === 1 ? '' : 's'}`,
    );
    button.append(name, meta);
    button.addEventListener('click', () => selectProject(project.id));
    container.appendChild(button);
  });
}

function renderNoProject() {
  pane.querySelector('#project-pane-title').textContent = 'Projects';
  TABS.forEach((tab) => {
    const panel = pane.querySelector(`#project-panel-${tab}`);
    panel.replaceChildren(element('div', 'project-empty', 'Select or create a project.'));
  });
}

async function loadProjects(preferredId = null) {
  projects = await request('/api/projects');
  renderProjectList();
  const saved = Storage.get(Storage.KEYS.CURRENT_PROJECT, '');
  const target = preferredId || saved;
  if (target && projects.some((project) => project.id === target)) {
    await selectProject(target, { updateUrl: false });
  } else if (projects.length) {
    await selectProject(projects[0].id, { updateUrl: false });
  } else {
    currentProject = null;
    renderNoProject();
  }
}

async function createProject(event) {
  event.preventDefault();
  const input = pane.querySelector('#project-create-name');
  const name = input.value.trim();
  if (!name) return;
  try {
    const project = await request('/api/projects', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
    input.value = '';
    projects.unshift(project);
    await selectProject(project.id);
    showToast('Project created');
  } catch (error) {
    showError(error.message || 'Could not create project');
  }
}

async function selectProject(projectId, { updateUrl = true } = {}) {
  try {
    currentProject = await request(`/api/projects/${encodeURIComponent(projectId)}`);
    Storage.set(Storage.KEYS.CURRENT_PROJECT, currentProject.id);
    pane.setAttribute('aria-label', `Project: ${currentProject.name}`);
    pane.querySelector('#project-pane-title').textContent = currentProject.name;
    renderProjectList();
    if (updateUrl) history.pushState({}, '', `/projects/${currentProject.id}`);
    await activateTab(currentTab);
  } catch (error) {
    showError(error.message || 'Could not open project');
  }
}

function card(label, value) {
  const item = element('div', 'project-card');
  item.append(element('div', 'project-muted', label), element('div', 'project-card-value', String(value)));
  return item;
}

async function renderOverview(panel) {
  const payload = await request(`/api/projects/${currentProject.id}/overview`);
  const grid = element('div', 'project-grid');
  grid.append(
    card('Conversations', payload.project.session_count || 0),
    card('Status', payload.project.status),
    card('Workspace', 'Managed'),
  );
  panel.append(grid);
  const heading = element('h3', '', 'Recent conversations');
  panel.appendChild(heading);
  if (!payload.recent_sessions.length) {
    panel.appendChild(element('div', 'project-empty', 'No conversations assigned yet.'));
    return;
  }
  payload.recent_sessions.forEach((session) => panel.appendChild(sessionRow(session)));
}

function sessionRow(session) {
  const row = element('div', 'project-session-row');
  const open = element('button', '', session.name || 'Untitled conversation');
  open.type = 'button';
  open.addEventListener('click', async () => {
    closeProjects();
    if (dependencies.sessionModule?.selectSession) {
      await dependencies.sessionModule.selectSession(session.id);
    }
  });
  row.append(open, element('span', 'project-muted', session.model || ''));
  return row;
}

async function renderConversations(panel) {
  const actions = element('div', 'project-settings-actions');
  const attach = element('button', 'project-action', 'Attach current chat');
  attach.type = 'button';
  attach.addEventListener('click', async () => {
    const sessionId = Storage.get(Storage.KEYS.CURRENT_SESSION, '');
    if (!sessionId) {
      showError('Open a saved conversation first');
      return;
    }
    try {
      await request(`/api/projects/${currentProject.id}/sessions/${encodeURIComponent(sessionId)}`, {
        method: 'PUT',
      });
      showToast('Conversation attached');
      await renderActivePanel();
      await refreshProjects();
    } catch (error) {
      showError(error.message || 'Could not attach conversation');
    }
  });
  actions.appendChild(attach);
  panel.appendChild(actions);
  const sessions = await request(`/api/projects/${currentProject.id}/sessions`);
  if (!sessions.length) {
    panel.appendChild(element('div', 'project-empty', 'No conversations assigned to this project.'));
    return;
  }
  sessions.forEach((session) => panel.appendChild(sessionRow(session)));
}

async function renderAgents(panel) {
  const form = element('form', 'project-create-form');
  const name = element('input');
  name.placeholder = 'Agent name';
  name.maxLength = 120;
  name.required = true;
  name.setAttribute('aria-label', 'Project agent name');
  const create = element('button', 'project-action primary', 'Add agent');
  create.type = 'submit';
  form.append(name, create);
  panel.appendChild(form);
  const list = element('div');
  panel.appendChild(list);

  const load = async () => {
    const agents = await request(`/api/projects/${currentProject.id}/agents`);
    list.replaceChildren();
    if (!agents.length) {
      list.appendChild(element('div', 'project-empty', 'No project agents yet.'));
      return;
    }
    agents.forEach((agent) => {
      const row = element('div', 'project-session-row');
      row.append(
        element('span', '', agent.name),
        element('span', 'project-muted', agent.model || 'Project default model'),
        element('span', 'project-muted', agent.is_default ? 'Default' : ''),
      );
      list.appendChild(row);
    });
  };
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await request(`/api/projects/${currentProject.id}/agents`, {
        method: 'POST',
        body: JSON.stringify({
          name: name.value.trim(),
          is_default: true,
        }),
      });
      name.value = '';
      await load();
      showToast('Project agent created');
    } catch (error) {
      showError(error.message || 'Could not create project agent');
    }
  });
  await load();
}

async function renderTasks(panel) {
  const form = element('form', 'project-settings-form');
  const name = element('input');
  name.placeholder = 'Task name';
  name.maxLength = 120;
  name.setAttribute('aria-label', 'Project task name');
  const prompt = element('textarea');
  prompt.placeholder = 'What should the project agent do?';
  prompt.rows = 3;
  prompt.required = true;
  prompt.setAttribute('aria-label', 'Project task prompt');
  const create = element('button', 'project-action primary', 'Add daily task');
  create.type = 'submit';
  form.append(name, prompt, create);
  panel.appendChild(form);
  const list = element('div');
  panel.appendChild(list);

  const load = async () => {
    const payload = await request(`/api/tasks?project_id=${encodeURIComponent(currentProject.id)}`);
    list.replaceChildren();
    if (!payload.tasks.length) {
      list.appendChild(element('div', 'project-empty', 'No project tasks yet.'));
      return;
    }
    payload.tasks.forEach((task) => {
      const row = element('div', 'project-session-row');
      row.append(
        element('span', '', task.name || 'Untitled task'),
        element('span', 'project-muted', `${task.status} · ${task.schedule || task.trigger_type}`),
      );
      list.appendChild(row);
    });
  };
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await request('/api/tasks', {
        method: 'POST',
        body: JSON.stringify({
          name: name.value.trim() || null,
          prompt: prompt.value.trim(),
          task_type: 'llm',
          trigger_type: 'schedule',
          schedule: 'daily',
          scheduled_time: '09:00',
          project_id: currentProject.id,
        }),
      });
      name.value = '';
      prompt.value = '';
      await load();
      showToast('Project task created');
    } catch (error) {
      showError(error.message || 'Could not create project task');
    }
  });
  await load();
}

async function renderFiles(panel) {
  const payload = await request(`/api/projects/${currentProject.id}/files`);
  panel.appendChild(element('div', 'project-muted', payload.workspace));
  if (!payload.entries.length) {
    panel.appendChild(element('div', 'project-empty', 'The managed project workspace is empty.'));
    return;
  }
  payload.entries.forEach((entry) => {
    const row = element('div', 'project-file-row');
    row.append(
      element('span', '', entry.type === 'directory' ? 'Directory' : 'File'),
      element('span', '', entry.path),
      element('span', 'project-muted', entry.size === undefined ? '' : `${entry.size} B`),
    );
    panel.appendChild(row);
  });
  if (payload.truncated) panel.appendChild(element('div', 'project-muted', 'File list truncated.'));
}

async function renderMemory(panel) {
  const form = element('form', 'project-create-form');
  const text = element('input');
  text.placeholder = 'Remember for this project';
  text.maxLength = 5000;
  text.required = true;
  text.setAttribute('aria-label', 'Project memory');
  const add = element('button', 'project-action primary', 'Remember');
  add.type = 'submit';
  form.append(text, add);
  panel.appendChild(form);
  const list = element('div');
  panel.appendChild(list);

  const load = async () => {
    const payload = await request(`/api/memory?project_id=${encodeURIComponent(currentProject.id)}`);
    list.replaceChildren();
    list.appendChild(element('div', 'project-muted', `Policy: ${payload.memory_mode}`));
    if (!payload.memory.length) {
      list.appendChild(element('div', 'project-empty', 'No memories visible under this policy.'));
      return;
    }
    payload.memory.forEach((memory) => {
      const row = element('div', 'project-session-row');
      row.append(
        element('span', '', memory.text),
        element('span', 'project-muted', memory.project_id ? 'Project' : 'Global'),
      );
      list.appendChild(row);
    });
  };
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await request('/api/memory/add', {
        method: 'POST',
        body: JSON.stringify({
          text: text.value.trim(),
          category: 'project',
          source: 'user',
          project_id: currentProject.id,
        }),
      });
      text.value = '';
      await load();
      showToast('Project memory added');
    } catch (error) {
      showError(error.message || 'Could not add project memory');
    }
  });
  await load();
}

async function renderModels(panel) {
  const form = element('form', 'project-settings-form');
  const endpoint = element('input');
  endpoint.placeholder = 'Model endpoint ID (optional)';
  endpoint.value = currentProject.settings?.default_endpoint_id || '';
  endpoint.setAttribute('aria-label', 'Default model endpoint ID');
  const model = element('input');
  model.placeholder = 'Default model name';
  model.value = currentProject.settings?.default_model || '';
  model.setAttribute('aria-label', 'Default project model');
  const save = element('button', 'project-action primary', 'Save model defaults');
  save.type = 'submit';
  form.append(
    element('label', '', 'Endpoint ID'),
    endpoint,
    element('label', '', 'Model'),
    model,
    save,
  );
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const settings = {
        ...(currentProject.settings || {}),
        default_endpoint_id: endpoint.value.trim(),
        default_model: model.value.trim(),
      };
      currentProject = await request(`/api/projects/${currentProject.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ settings }),
      });
      showToast('Project model defaults saved');
    } catch (error) {
      showError(error.message || 'Could not save model defaults');
    }
  });
  panel.appendChild(form);
}

async function renderSettings(panel) {
  const form = element('form', 'project-settings-form');
  const name = element('input');
  name.value = currentProject.name;
  name.maxLength = 120;
  name.required = true;
  name.setAttribute('aria-label', 'Project name');
  const description = element('textarea');
  description.value = currentProject.description || '';
  description.rows = 5;
  description.maxLength = 4000;
  description.setAttribute('aria-label', 'Project description');
  const mode = element('select');
  mode.setAttribute('aria-label', 'Project memory mode');
  [
    ['inherit', 'Inherit owner memory'],
    ['project_plus_global', 'Project and global memory'],
    ['project_only', 'Project memory only'],
  ].forEach(([value, label]) => {
    const option = element('option', '', label);
    option.value = value;
    option.selected = (currentProject.settings?.memory_mode || 'inherit') === value;
    mode.appendChild(option);
  });
  const actions = element('div', 'project-settings-actions');
  const save = element('button', 'project-action primary', 'Save');
  save.type = 'submit';
  const archive = element('button', 'project-action danger', 'Archive');
  archive.type = 'button';
  actions.append(save, archive);
  form.append(
    element('label', '', 'Name'),
    name,
    element('label', '', 'Description'),
    description,
    element('label', '', 'Memory policy (used by 0.2.1)'),
    mode,
    actions,
  );
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const settings = { ...(currentProject.settings || {}), memory_mode: mode.value };
      currentProject = await request(`/api/projects/${currentProject.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          name: name.value.trim(),
          description: description.value,
          settings,
        }),
      });
      await refreshProjects();
      pane.querySelector('#project-pane-title').textContent = currentProject.name;
      showToast('Project saved');
    } catch (error) {
      showError(error.message || 'Could not save project');
    }
  });
  archive.addEventListener('click', async () => {
    const confirmed = dependencies.uiModule?.styledConfirm
      ? await dependencies.uiModule.styledConfirm('Archive this project?', {
          confirmText: 'Archive',
          danger: true,
        })
      : window.confirm('Archive this project?');
    if (!confirmed) return;
    try {
      await request(`/api/projects/${currentProject.id}`, { method: 'DELETE' });
      Storage.remove(Storage.KEYS.CURRENT_PROJECT);
      currentProject = null;
      await loadProjects();
      history.pushState({}, '', '/projects');
      showToast('Project archived');
    } catch (error) {
      showError(error.message || 'Could not archive project');
    }
  });
  panel.appendChild(form);
}

async function renderActivePanel() {
  if (!currentProject) return;
  const panel = pane.querySelector(`#project-panel-${currentTab}`);
  panel.replaceChildren(element('div', 'project-empty', 'Loading…'));
  try {
    panel.replaceChildren();
    if (currentTab === 'overview') await renderOverview(panel);
    if (currentTab === 'conversations') await renderConversations(panel);
    if (currentTab === 'agents') await renderAgents(panel);
    if (currentTab === 'tasks') await renderTasks(panel);
    if (currentTab === 'files') await renderFiles(panel);
    if (currentTab === 'memory') await renderMemory(panel);
    if (currentTab === 'models') await renderModels(panel);
    if (currentTab === 'settings') await renderSettings(panel);
  } catch (error) {
    panel.replaceChildren(element('div', 'project-empty', error.message || 'Could not load project section'));
  }
}

async function activateTab(tab) {
  if (!TABS.includes(tab)) tab = 'overview';
  currentTab = tab;
  pane.querySelectorAll('[data-project-tab]').forEach((button) => {
    button.setAttribute('aria-selected', String(button.dataset.projectTab === tab));
  });
  TABS.forEach((name) => {
    pane.querySelector(`#project-panel-${name}`).hidden = name !== tab;
  });
  await renderActivePanel();
}

async function refreshProjects() {
  const selected = currentProject?.id;
  projects = await request('/api/projects');
  if (selected) {
    const summary = projects.find((project) => project.id === selected);
    if (summary) Object.assign(summary, currentProject);
  }
  renderProjectList();
}

export async function openProjects(projectId = null) {
  ensurePane();
  pane.hidden = false;
  document.body.style.overflow = 'hidden';
  try {
    await loadProjects(projectId);
    pane.querySelector('#project-create-name')?.focus();
  } catch (error) {
    renderNoProject();
    showError(error.message || 'Could not load projects');
  }
}

export function closeProjects() {
  if (!pane) return;
  pane.hidden = true;
  document.body.style.overflow = '';
  if (window.location.pathname.startsWith('/projects')) {
    history.pushState({}, '', '/');
  }
}

export function initProjectCore(options = {}) {
  dependencies = options;
  ensurePane();
  document.getElementById('tool-projects-btn')
    ?.addEventListener('click', () => openProjects());
}

export default {
  initProjectCore,
  openProjects,
  closeProjects,
};
