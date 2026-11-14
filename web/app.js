const statusNode = document.querySelector('#status');
const filters = document.querySelector('#filters');
let current = null;
let requestGeneration = 0;

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}

function text(tag, value) {
  const node = document.createElement(tag);
  node.textContent = typeof value === 'object' ? JSON.stringify(value) : String(value ?? '未知');
  return node;
}

function table(container, rows) {
  container.replaceChildren();
  if (!rows.length) {
    container.append(text('p', '当前范围没有记录'));
    return;
  }
  const columns = Array.from(new Set(rows.flatMap(row => Object.keys(row))));
  const grid = document.createElement('table');
  const head = document.createElement('tr');
  for (const column of columns) head.append(text('th', column));
  const thead = document.createElement('thead');
  thead.append(head);
  grid.append(thead);
  const body = document.createElement('tbody');
  for (const row of rows) {
    const line = document.createElement('tr');
    for (const column of columns) line.append(text('td', row[column]));
    body.append(line);
  }
  grid.append(body);
  container.append(grid);
}

function ratio(value) {
  return value === null || value === undefined ? '无观测' : `${(value * 100).toFixed(1)}%`;
}

function renderValidation(validation) {
  const container = document.querySelector('#validation');
  container.replaceChildren();
  container.append(text('p', `分组交叉验证：${validation.folds} 折，覆盖售后事件 ${validation.cases} 个，复核样本 ${validation.tickets} 张`));
  for (const scheme of validation.schemes) {
    const block = document.createElement('div');
    block.className = 'scheme';
    block.append(text('h3', `候选方案：${scheme.name}`));
    const summary = document.createElement('dl');
    summary.append(text('dt', '自动覆盖'), text('dd', ratio(scheme.coverage)),
                   text('dt', '自动准确率'), text('dd', ratio(scheme.accuracy_auto)),
                   text('dt', '人工工作量'), text('dd', ratio(scheme.workload)));
    block.append(summary);
    const holder = document.createElement('div');
    table(holder, scheme.causes.map(cause => ({'原因': cause.label, '复核样本': cause.support, '自动正确': cause.auto_correct,
      '自动误判': cause.auto_wrong, '转人工': cause.to_human, '检出率': ratio(cause.recall), '误判率': ratio(cause.miss)})));
    block.append(holder);
    container.append(block);
  }
  const notes = document.createElement('ul');
  for (const note of validation.notes) notes.append(text('li', note));
  container.append(notes);
}

async function releases() {
  const entries = await api('/api/releases');
  const list = document.querySelector('#releases');
  list.replaceChildren();
  if (!entries.length) {
    list.append(text('li', '还没有训练过的版本'));
    return;
  }
  for (const entry of entries) {
    const item = document.createElement('li');
    const view = text('button', entry.name);
    view.type = 'button';
    view.addEventListener('click', async () => {
      try {
        const full = await api(`/api/releases/${entry.id}`);
        renderValidation(full.validation);
        statusNode.textContent = `正在查看版本验证：${entry.name}`;
      } catch (error) {
        statusNode.textContent = error.message;
      }
    });
    item.append(view, text('small', `${entry.created_at}，分类：${entry.taxonomy.join('、')}`));
    if (entry.published_scheme) {
      const scheme = entry.schemes.find(item => item.id === entry.published_scheme);
      item.append(text('mark', `已发布：${scheme ? scheme.name : entry.published_scheme}`));
    } else {
      const select = document.createElement('select');
      for (const scheme of entry.schemes) {
        const option = text('option', scheme.name);
        option.value = scheme.id;
        select.append(option);
      }
      const publish = text('button', '发布');
      publish.type = 'button';
      publish.addEventListener('click', async () => {
        try {
          await api(`/api/releases/${entry.id}/publish`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({scheme: select.value})});
          statusNode.textContent = `已发布：${entry.name}`;
          await releases();
        } catch (error) {
          statusNode.textContent = error.message;
        }
      });
      item.append(select, publish);
    }
    list.append(item);
  }
}

function render(value, savedTitle = '') {
  current = value;
  const summary = document.querySelector('#summary');
  summary.replaceChildren();
  for (const [key, amount] of Object.entries(value.result.summary)) {
    summary.append(text('dt', key), text('dd', amount));
  }
  document.querySelector('#notes').replaceChildren(...value.result.notes.map(note => text('li', note)));
  document.querySelector('#digest').textContent = `资料指纹：${value.digest}`;
  table(document.querySelector('#results'), value.result.rows);
  statusNode.textContent = savedTitle ? `正在查看保存的分析：${savedTitle}` : '分析已更新';
  filters.elements.cutoff.value = value.options.cutoff;
  filters.elements.group.value = value.options.group;
}

async function refresh() {
  const generation = ++requestGeneration;
  const query = new URLSearchParams(new FormData(filters));
  statusNode.textContent = '正在分析';
  try {
    const result = await api(`/api/view?${query}`);
    if (generation === requestGeneration) render(result);
  } catch (error) {
    if (generation === requestGeneration) {
      current = null;
      statusNode.textContent = error.message;
    }
  }
}

async function history() {
  const entries = await api('/api/analyses');
  const list = document.querySelector('#history');
  list.replaceChildren();
  for (const entry of entries) {
    const item = document.createElement('li');
    const button = text('button', entry.title);
    button.type = 'button';
    button.addEventListener('click', async () => {
      const generation = ++requestGeneration;
      try {
        const saved = await api(`/api/analyses/${entry.id}`);
        if (generation === requestGeneration) render(saved, saved.title);
      } catch (error) {
        statusNode.textContent = error.message;
      }
    });
    item.append(button, text('small', entry.created_at));
    list.append(item);
  }
}

filters.addEventListener('submit', event => {
  event.preventDefault();
  refresh();
});

document.querySelector('#train').addEventListener('submit', async event => {
  event.preventDefault();
  if (!current) return;
  statusNode.textContent = '正在训练与验证';
  try {
    const release = await api('/api/releases', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: event.target.elements.name.value, options: current.options})});
    renderValidation(release.validation);
    statusNode.textContent = `版本已保存：${release.name}`;
    await releases();
  } catch (error) {
    statusNode.textContent = error.message;
  }
});

document.querySelector('#suggest').addEventListener('click', async () => {
  const query = new URLSearchParams(new FormData(filters));
  statusNode.textContent = '正在生成建议';
  try {
    const data = await api(`/api/suggestions?${query}`);
    const summary = document.querySelector('#suggest-summary');
    summary.replaceChildren();
    for (const [key, amount] of Object.entries(data.summary)) summary.append(text('dt', key), text('dd', amount));
    document.querySelector('#suggest-notes').replaceChildren(...data.notes.map(note => text('li', note)));
    table(document.querySelector('#suggestions'), data.rows.map(row => ({'工单': row.ticket, '事件': row.case, '建议原因': row.label,
      '置信度': row.confidence, '决定': row.decision === 'auto' ? '自动' : '转人工', '理由': row.reasons.join('；') || '通过阈值',
      '识别版本': row.release, '生成时点': row.computed_cutoff})));
    statusNode.textContent = '建议已更新';
  } catch (error) {
    statusNode.textContent = error.message;
  }
});

document.querySelector('#save').addEventListener('submit', async event => {
  event.preventDefault();
  if (!current) return;
  try {
    const saved = await api('/api/analyses', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({title: event.target.elements.title.value, options: current.options})});
    render(saved, saved.title);
    await history();
  } catch (error) {
    statusNode.textContent = error.message;
  }
});

document.querySelector('#source').addEventListener('click', async () => {
  try {
    const data = await api(`/api/source?table=${encodeURIComponent(document.querySelector('#tables').value)}`);
    table(document.querySelector('#raw'), data.rows);
  } catch (error) {
    statusNode.textContent = error.message;
  }
});

async function start() {
  const catalog = await api('/api/catalog');
  document.querySelector('#description').textContent = catalog.description;
  filters.elements.cutoff.min = catalog.min_cutoff;
  filters.elements.cutoff.max = catalog.max_cutoff;
  filters.elements.cutoff.value = catalog.default_cutoff;
  const groups = [['', '全部'], ...catalog.groups.map(group => [group, group])];
  for (const [key, label] of groups) {
    const option = text('option', label);
    option.value = key;
    filters.elements.group.append(option);
  }
  for (const name of Object.keys(catalog.tables)) {
    const option = text('option', `${name}（${catalog.tables[name]}）`);
    option.value = name;
    document.querySelector('#tables').append(option);
  }
  await refresh();
  await history();
  await releases();
}

start().catch(error => { statusNode.textContent = error.message; });
