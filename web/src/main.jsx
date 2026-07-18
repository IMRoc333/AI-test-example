import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

const HISTORY_KEY = 'auto-prd-agent-history'
const CONFIG_KEY = 'auto-prd-agent-model-config'
const DOC_TYPES = ['需求规范', '业务规则', '历史缺陷', '测试经验', '接口文档']

const defaultConfig = {
  provider: 'openai_compatible',
  apiKey: '',
  baseUrl: 'https://api.deepseek.com',
  modelName: 'deepseek-chat',
  embeddingModel: 'text-embedding-3-small',
  visionModel: 'qwen-vl-plus',
}

const headers = ['id', 'module', 'precondition', 'step', 'expected', 'priority', 'design_strategy']
const headerNames = {
  id: '用例ID',
  module: '模块',
  precondition: '前置条件',
  step: '操作步骤',
  expected: '预期结果',
  priority: '优先级',
  design_strategy: '设计策略',
}

async function requestJson(url, options = {}) {
  const res = await fetch(url, options)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `请求失败：${res.status}`)
  return data
}

function loadJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback
  } catch {
    return fallback
  }
}

function loadArray(key) {
  try {
    const raw = localStorage.getItem(key)
    const value = raw ? JSON.parse(raw) : []
    return Array.isArray(value) ? value : []
  } catch {
    return []
  }
}

function toMarkdown(rows) {
  if (!rows.length) return ''
  const clean = (value) => String(value ?? '').replace(/\|/g, '\\|').replace(/\n/g, '<br>')
  return [
    `| ${headers.map((key) => headerNames[key]).join(' | ')} |`,
    `| ${headers.map(() => '---').join(' | ')} |`,
    ...rows.map((row) => `| ${headers.map((key) => clean(row[key])).join(' | ')} |`),
  ].join('\n')
}

function toCsv(rows) {
  if (!rows.length) return ''
  const cell = (value) => `"${String(value ?? '').replace(/"/g, '""')}"`
  return [headers.map((key) => headerNames[key]).join(','), ...rows.map((row) => headers.map((key) => cell(row[key])).join(','))].join('\n')
}

function download(name, content, type) {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

function App() {
  const [view, setView] = useState('workbench')
  const [config, setConfig] = useState(() => loadJson(CONFIG_KEY, defaultConfig))
  const [prdText, setPrdText] = useState('')
  const [cases, setCases] = useState([])
  const [ragContext, setRagContext] = useState('')
  const [sources, setSources] = useState([])
  const [report, setReport] = useState(null)
  const [trace, setTrace] = useState([])
  const [requirementAnalysis, setRequirementAnalysis] = useState(null)
  const [analysisDraft, setAnalysisDraft] = useState('')
  const [analysisConfirmed, setAnalysisConfirmed] = useState(false)
  const [suggestedRules, setSuggestedRules] = useState([])
  const [multiAgentTrace, setMultiAgentTrace] = useState([])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [targetScore, setTargetScore] = useState(85)
  const [maxRounds, setMaxRounds] = useState(2)
  const [useKb, setUseKb] = useState(true)
  const [useHistory, setUseHistory] = useState(true)
  const [enableVisionParse, setEnableVisionParse] = useState(false)
  const [kbItems, setKbItems] = useState([])
  const [kbDocType, setKbDocType] = useState(DOC_TYPES[0])
  const [kbCollection, setKbCollection] = useState('knowledge')
  const [history, setHistory] = useState(() => loadArray(HISTORY_KEY))

  useEffect(() => {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, 30)))
  }, [history])

  useEffect(() => {
    localStorage.setItem(CONFIG_KEY, JSON.stringify(config))
  }, [config])

  const stats = useMemo(() => {
    const modules = new Set(cases.map((item) => item.module).filter(Boolean))
    const p0 = cases.filter((item) => item.priority === 'P0').length
    return { total: cases.length, modules: modules.size, p0 }
  }, [cases])

  const progress = useMemo(() => ([
    { name: 'PRD 输入', done: Boolean(prdText.trim()) },
    { name: '需求分析', done: Boolean(requirementAnalysis) },
    { name: '人工确认', done: analysisConfirmed },
    { name: '用例生成', done: cases.length > 0 },
    { name: '评估优化', done: Boolean(report) || trace.length > 0 },
    { name: '规则沉淀', done: suggestedRules.length > 0 },
  ]), [prdText, requirementAnalysis, analysisConfirmed, cases.length, report, trace.length, suggestedRules.length])

  function resetAnalysisState() {
    setRequirementAnalysis(null)
    setAnalysisDraft('')
    setAnalysisConfirmed(false)
    setSuggestedRules([])
    setMultiAgentTrace([])
  }

  function updatePrdText(value) {
    setPrdText(value)
    setCases([])
    setReport(null)
    setTrace([])
    resetAnalysisState()
  }

  function updateConfig(key, value) {
    setConfig((prev) => ({ ...prev, [key]: value }))
    setNotice('模型配置已自动保存到本机浏览器')
  }

  function resetConfig() {
    setConfig(defaultConfig)
    localStorage.removeItem(CONFIG_KEY)
    setNotice('已恢复默认模型配置')
  }

  function saveConfigNow() {
    localStorage.setItem(CONFIG_KEY, JSON.stringify(config))
    setNotice('模型配置已保存，可以回到工作台开始生成')
  }

  function saveLocalHistory(label, nextCases = cases, nextReport = report, nextTrace = trace) {
    const item = {
      id: crypto.randomUUID(),
      label,
      createdAt: new Date().toISOString(),
      prdText,
      cases: nextCases,
      report: nextReport,
      trace: nextTrace,
      score: nextReport?.score ?? null,
      rounds: nextTrace?.length || 0,
    }
    setHistory((prev) => [item, ...prev].slice(0, 30))
  }

  async function parseFile(file) {
    setError('')
    setNotice('')
    setBusy('解析文件')
    const form = new FormData()
    form.append('file', file)
    form.append('config', JSON.stringify(config))
    form.append('enableVision', String(enableVisionParse))
    try {
      const data = await requestJson('/api/parse-file', { method: 'POST', body: form })
      updatePrdText(data.text)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  async function analyzeRequirement() {
    setError('')
    setNotice('')
    setBusy('需求分析')
    setReport(null)
    setTrace([])
    setCases([])
    setSuggestedRules([])
    try {
      const data = await requestJson('/api/analyze-requirement', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config, prdText, useKb, useHistory }),
      })
      const analysis = data.analysis || {}
      setRequirementAnalysis(analysis)
      setAnalysisDraft(JSON.stringify(analysis, null, 2))
      setAnalysisConfirmed(false)
      setRagContext(data.ragContext || '')
      setSources(data.sources || [])
      setMultiAgentTrace(data.agentTrace || [])
      setNotice('需求分析已完成，请确认模块树后再生成用例')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  function confirmAnalysis() {
    setError('')
    try {
      const parsed = JSON.parse(analysisDraft)
      setRequirementAnalysis(parsed)
      setAnalysisConfirmed(true)
      setNotice('模块树已确认，可以生成测试用例')
    } catch {
      setError('需求分析 JSON 格式不正确，请修正后再确认。')
    }
  }

  async function generate() {
    setError('')
    setNotice('')
    setBusy('生成用例')
    setReport(null)
    setTrace([])
    setSuggestedRules([])
    try {
      let analysisContext = requirementAnalysis
      if (analysisDraft.trim()) {
        analysisContext = JSON.parse(analysisDraft)
      }
      const data = await requestJson('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config, prdText, useKb, useHistory, analysisContext }),
      })
      const nextCases = data.cases || []
      setCases(nextCases)
      setRagContext(data.ragContext || '')
      setSources(data.sources || [])
      setMultiAgentTrace((prev) => [...prev, ...(data.agentTrace || [])])
      if (nextCases.length) saveLocalHistory('生成测试用例', nextCases, null, [])
      if (!nextCases.length) setError('模型没有返回有效的 JSON 用例，请检查模型名称、提示词或输出格式。')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  async function evaluate() {
    setError('')
    setNotice('')
    setBusy('质量评估')
    try {
      const data = await requestJson('/api/evaluate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config, prdText, cases, ragContext }),
      })
      setReport(data.report)
      saveLocalHistory('评估测试用例', cases, data.report, trace)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  async function optimize() {
    setError('')
    setNotice('')
    setBusy('Agent 优化')
    try {
 const data = await requestJson('/api/agent-optimize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config, prdText, cases, ragContext, targetScore, maxRounds }),
      })
      const nextCases = data.cases || []
      const nextReport = data.report || null
      const nextTrace = data.trace || []
      const nextRules = data.suggestedRules || []
      setCases(nextCases)
      setReport(nextReport)
      setTrace(nextTrace)
      setSuggestedRules(nextRules)
      saveLocalHistory('Agent 自动优化', nextCases, nextReport, nextTrace)
      if (nextRules.length) setNotice(`Agent 已提炼 ${nextRules.length} 条可沉淀规则，可保存到知识库`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  async function saveSuggestedRules() {
    setError('')
    setNotice('')
    setBusy('沉淀规则')
    try {
      const data = await requestJson('/api/rules/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config, rules: suggestedRules, sourcePrd: prdText }),
      })
      setNotice(`已沉淀到知识库：${data.count} 条规则`)
      setSuggestedRules([])
      if (kbCollection === 'knowledge') await refreshKb('knowledge')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  async function saveHistoryCase() {
    setError('')
    setNotice('')
    setBusy('保存历史用例')
    try {
      const summary = `历史用例：${new Date().toLocaleString()}，${cases.length} 条，评分 ${report?.score ?? '--'}`
      const data = await requestJson('/api/history/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config, prdText, cases, summary }),
      })
      setNotice(`已保存到历史用例库：${data.count} 条用例`)
      if (kbCollection === 'history') await refreshKb('history')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  async function refreshKb(collectionType = kbCollection) {
    setError('')
    setNotice('')
    setBusy(collectionType === 'history' ? '刷新历史用例' : '刷新知识库')
    try {
      const data = await requestJson('/api/kb/list', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config, collectionType }),
      })
      setKbItems(data.items || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  async function switchKbCollection(collectionType) {
    setKbCollection(collectionType)
    await refreshKb(collectionType)
  }

  async function uploadKnowledge(file, docType) {
    setError('')
    setNotice('')
    setBusy('上传知识')
    const form = new FormData()
    form.append('config', JSON.stringify(config))
    form.append('docType', docType)
    form.append('file', file)
    try {
      await requestJson('/api/kb/upload', { method: 'POST', body: form })
      await refreshKb('knowledge')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  async function deleteKnowledge(docId, collectionType = kbCollection) {
    setError('')
    setNotice('')
    setBusy(collectionType === 'history' ? '删除历史用例' : '删除知识')
    try {
      await requestJson('/api/kb/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config, docId, collectionType }),
      })
      await refreshKb(collectionType)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  function restoreHistory(item) {
    setPrdText(item.prdText || '')
    setCases(item.cases || [])
    setReport(item.report || null)
    setTrace(item.trace || [])
    resetAnalysisState()
    setView('workbench')
  }

  const pageTitle = view === 'workbench' ? '用例生成工作台' : view === 'knowledge' ? '知识库管理' : view === 'history' ? '历史任务' : '模型设置'
  const pageDesc = view === 'workbench'
    ? '上传或粘贴 PRD，结合知识库生成测试用例，并通过评估与 Agent 迭代提升质量。'
    : view === 'knowledge'
      ? '管理知识文档与历史用例，让后续需求可以复用测试经验。'
      : view === 'history'
        ? '查看本机保存的生成、评估和优化记录，方便继续调试或面试演示。'
        : '集中管理国产大模型、OpenAI-compatible 接口和向量模型配置。'

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="mark">测</div>
          <div>
            <h1>PRD 测试用例生成平台</h1>
            <p>知识库增强 · 自动评估 · Agent 优化</p>
          </div>
        </div>

        <nav className="nav">
          <button className={view === 'workbench' ? 'active' : ''} onClick={() => setView('workbench')}>用例工作台</button>
          <button className={view === 'knowledge' ? 'active' : ''} onClick={() => { setView('knowledge'); refreshKb(kbCollection) }}>知识库管理</button>
          <button className={view === 'history' ? 'active' : ''} onClick={() => setView('history')}>历史任务</button>
          <button className={view === 'settings' ? 'active' : ''} onClick={() => setView('settings')}>模型设置</button>
        </nav>

        <section className="panel model-summary">
          <h2>当前模型</h2>
          <strong>{config.modelName || '未配置'}</strong>
          <span>{config.provider === 'openai_compatible' ? 'OpenAI-compatible' : 'Gemini'}</span>
          <button onClick={() => setView('settings')}>修改配置</button>
        </section>

        <section className="panel">
          <h2>优化策略</h2>
          <label>目标评分</label>
          <input type="number" min="50" max="100" step="5" value={targetScore} onChange={(e) => setTargetScore(Number(e.target.value))} />
          <label>最大迭代轮数</label>
          <input type="number" min="1" max="5" value={maxRounds} onChange={(e) => setMaxRounds(Number(e.target.value))} />
          <div className="checks">
            <label><input type="checkbox" checked={useKb} onChange={(e) => setUseKb(e.target.checked)} /> 启用知识库召回</label>
            <label><input type="checkbox" checked={useHistory} onChange={(e) => setUseHistory(e.target.checked)} /> 启用历史案例参考</label>
            <label><input type="checkbox" checked={enableVisionParse} onChange={(e) => setEnableVisionParse(e.target.checked)} /> 启用 PDF / 图片多模态解析</label>
          </div>
        </section>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <h2>{pageTitle}</h2>
            <p>{pageDesc}</p>
          </div>
          {view === 'workbench' && (
            <div className="actions">
              <button onClick={() => setView('settings')}>切换模型</button>
              <button onClick={analyzeRequirement} disabled={busy || !prdText}>需求分析</button>
              <button className="primary" onClick={generate} disabled={busy || !prdText || !analysisConfirmed}>生成用例</button>
            </div>
          )}
        </header>

        {error && <div className="error">{error}</div>}
        {notice && <div className="notice">{notice}</div>}

        {view === 'workbench' && (
          <>
            <WorkflowProgress steps={progress} />
            <section className="grid">
              <div className="card prd-card">
                <div className="card-head">
                  <h3>PRD 输入</h3>
                  <label className="upload">上传文件<input type="file" accept=".txt,.md,.pdf,.png,.jpg,.jpeg,.webp" onChange={(e) => e.target.files?.[0] && parseFile(e.target.files[0])} /></label>
                </div>
                <textarea value={prdText} onChange={(e) => updatePrdText(e.target.value)} placeholder="粘贴 PRD 文本，或上传 txt / md / pdf / UI 图片。PDF 或图片含原型图时，可开启多模态解析。" />
              </div>

              <div className="card score-card">
                <h3>质量概览</h3>
                <div className="score-row">
                  <div><strong>{stats.total}</strong><span>用例数</span></div>
                  <div><strong>{stats.modules}</strong><span>覆盖模块</span></div>
                  <div><strong>{stats.p0}</strong><span>P0 用例</span></div>
                </div>
                <div className="score-box"><span>AI 评分</span><strong>{report?.score ?? '--'}</strong></div>
                <p>{report?.summary || '生成用例后，可进行质量评估或启动 Agent 自动优化。'}</p>
                <div className="actions vertical">
                  <button onClick={evaluate} disabled={busy || !cases.length}>质量评估</button>
                  <button className="primary" onClick={optimize} disabled={busy || !cases.length}>Agent 优化</button>
                  <button onClick={saveHistoryCase} disabled={busy || !cases.length}>保存为历史用例</button>
                </div>
              </div>
            </section>

            <RequirementAnalysisPanel
              analysis={requirementAnalysis}
              draft={analysisDraft}
              setDraft={setAnalysisDraft}
              confirmed={analysisConfirmed}
              onAnalyze={analyzeRequirement}
              onConfirm={confirmAnalysis}
              busy={busy}
              disabled={!prdText}
            />

            <section className="grid lower">
              <CasesPanel cases={cases} busy={busy} />
              <TracePanel trace={trace} sources={sources} suggestedRules={suggestedRules} onSaveRules={saveSuggestedRules} busy={busy} multiAgentTrace={multiAgentTrace} />
            </section>
          </>
        )}

        {view === 'knowledge' && (
          <KnowledgeView
            items={kbItems}
            busy={busy}
            docType={kbDocType}
            setDocType={setKbDocType}
            collection={kbCollection}
            onSwitchCollection={switchKbCollection}
            onRefresh={refreshKb}
            onUpload={uploadKnowledge}
            onDelete={deleteKnowledge}
          />
        )}

        {view === 'history' && (
          <HistoryView history={history} onRestore={restoreHistory} onClear={() => setHistory([])} />
        )}

        {view === 'settings' && (
          <SettingsView config={config} updateConfig={updateConfig} resetConfig={resetConfig} saveConfigNow={saveConfigNow} />
        )}
      </main>
    </div>
  )
}

function WorkflowProgress({ steps }) {
  const activeIndex = Math.min(steps.findIndex((step) => !step.done), steps.length - 1)
  const current = activeIndex < 0 ? steps.length - 1 : activeIndex

  return (
    <section className="workflow">
      {steps.map((step, index) => (
        <div className={`workflow-step ${step.done ? 'done' : ''} ${index === current ? 'current' : ''}`} key={step.name}>
          <span>{step.done ? '✓' : index + 1}</span>
          <b>{step.name}</b>
        </div>
      ))}
    </section>
  )
}

function SettingsView({ config, updateConfig, resetConfig, saveConfigNow }) {
  return (
    <section className="settings-grid">
      <div className="card settings-main">
        <div className="card-head">
          <h3>API 配置</h3>
          <div className="actions">
            <button onClick={resetConfig}>恢复默认</button>
            <button className="primary" onClick={saveConfigNow}>保存配置</button>
          </div>
        </div>
        <div className="form-grid">
          <label>接口类型</label>
          <select value={config.provider} onChange={(e) => updateConfig('provider', e.target.value)}>
            <option value="openai_compatible">OpenAI-compatible 通用接口</option>
            <option value="gemini">Gemini</option>
          </select>
          <label>API Key</label>
          <input type="password" value={config.apiKey} onChange={(e) => updateConfig('apiKey', e.target.value)} placeholder="请输入模型平台密钥" />
          <label>Base URL</label>
          <input value={config.baseUrl} onChange={(e) => updateConfig('baseUrl', e.target.value)} placeholder="例如 https://api.deepseek.com" />
          <label>对话模型</label>
          <input value={config.modelName} onChange={(e) => updateConfig('modelName', e.target.value)} placeholder="例如 deepseek-chat" />
          <label>向量模型</label>
          <input value={config.embeddingModel} onChange={(e) => updateConfig('embeddingModel', e.target.value)} placeholder="例如 text-embedding-3-small" />
          <label>视觉模型</label>
          <input value={config.visionModel} onChange={(e) => updateConfig('visionModel', e.target.value)} placeholder="例如 qwen-vl-plus / qwen3-vl-flash" />
        </div>
      </div>

      <div className="card settings-help">
        <h3>配置说明</h3>
        <div className="hint-list">
          <p><b>自动保存</b><span>配置会保存到当前浏览器的 localStorage，刷新页面后仍会保留。API Key 只保存在本机浏览器。</span></p>
          <p><b>国产 API</b><span>优先选择 OpenAI-compatible，填写平台提供的 Base URL、API Key 和模型名。</span></p>
          <p><b>知识库</b><span>向量模型需要支持 embeddings 接口，否则知识库召回会失败。</span></p>
          <p><b>多模态解析</b><span>上传 UI 图、原型图或扫描 PDF 时，开启多模态解析，并填写支持 image_url 的视觉模型。</span></p>
        </div>
      </div>
    </section>
  )
}

function RequirementAnalysisPanel({ analysis, draft, setDraft, confirmed, onAnalyze, onConfirm, busy, disabled }) {
  const modules = Array.isArray(analysis?.modules) ? analysis.modules : []
  const questions = Array.isArray(analysis?.missing_questions) ? analysis.missing_questions : []
  const rules = Array.isArray(analysis?.business_rules) ? analysis.business_rules : []

  return (
    <section className="card analysis-card">
      <div className="card-head">
        <div>
          <h3>需求结构化 / 模块树确认</h3>
          <p>先把不规范 PRD 转成测试模块树，人工确认后再生成用例。</p>
        </div>
        <div className="actions">
          <button onClick={onAnalyze} disabled={busy || disabled}>重新分析</button>
          <button className="primary" onClick={onConfirm} disabled={busy || !draft}>确认模块树</button>
        </div>
      </div>

      {!analysis && <p className="empty">点击“需求分析”后，这里会展示模块、测试点、缺失问题和 AI 假设。</p>}

      {analysis && (
        <div className="analysis-grid">
          <div className="analysis-preview">
            <div className={`confirm-banner ${confirmed ? 'confirmed' : ''}`}>
              {confirmed ? '已确认：生成用例会优先使用这份模块树' : '待确认：请检查模块树和缺失问题'}
            </div>
            <p className="analysis-summary">{analysis.summary || '暂无摘要'}</p>

            <h4>测试模块</h4>
            <div className="module-list">
              {modules.map((module, index) => (
                <div className="module-item" key={`${module.name || 'module'}-${index}`}>
                  <b>{module.name || `模块 ${index + 1}`}</b>
                  <div className="tag-row">
                    {(module.test_points || []).map((point) => <span key={point}>{point}</span>)}
                  </div>
                  {Array.isArray(module.risks) && module.risks.length > 0 && (
                    <p>风险：{module.risks.join('、')}</p>
                  )}
                </div>
              ))}
            </div>

            <h4>明确规则</h4>
            <ul className="compact-list">{rules.map((rule) => <li key={rule}>{rule}</li>)}</ul>

            <h4>待确认问题</h4>
            <ul className="compact-list warning-list">{questions.map((question) => <li key={question}>{question}</li>)}</ul>
          </div>
          <div className="analysis-editor">
            <label>可编辑 JSON</label>
            <textarea value={draft} onChange={(e) => setDraft(e.target.value)} />
          </div>
        </div>
      )}
    </section>
  )
}

function CasesPanel({ cases, busy }) {
  return (
    <div className="card cases-card">
      <div className="card-head">
        <h3>测试用例</h3>
        <div className="actions">
          <button disabled={!cases.length} onClick={() => download('测试用例.json', JSON.stringify(cases, null, 2), 'application/json')}>JSON</button>
          <button disabled={!cases.length} onClick={() => download('测试用例.csv', toCsv(cases), 'text/csv')}>CSV</button>
          <button disabled={!cases.length} onClick={() => download('测试用例.md', toMarkdown(cases), 'text/markdown')}>Markdown</button>
        </div>
      </div>
      <div className="status-line">{busy ? `当前任务：${busy}` : '就绪'}</div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>用例ID</th><th>模块</th><th>操作步骤</th><th>预期结果</th><th>优先级</th></tr></thead>
          <tbody>
            {cases.map((item, index) => (
              <tr key={item.id || index}>
                <td>{item.id || `TC_${index + 1}`}</td>
                <td>{item.module || '-'}</td>
                <td>{item.step || '-'}</td>
                <td>{item.expected || '-'}</td>
                <td><span className={`pill ${item.priority || ''}`}>{item.priority || '-'}</span></td>
              </tr>
            ))}
            {!cases.length && <tr><td colSpan="5" className="empty">暂无测试用例</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function TracePanel({ trace, sources, suggestedRules, onSaveRules, busy, multiAgentTrace }) {
  return (
    <div className="card trace-card">
      <h3>Multi-Agent 协作轨迹</h3>
      {multiAgentTrace.length ? multiAgentTrace.map((step, index) => (
        <div className="trace multi-agent-step" key={`${step.agent}-${index}`}>
          <b>{step.agent}</b>
          <span>{step.action || 'finish'}</span>
          <p>{step.summary}</p>
          {step.output && (
            <pre>{JSON.stringify(step.output, null, 2)}</pre>
          )}
        </div>
      )) : <p className="empty">完成需求分析后，这里会展示文档解析 Agent、模块生成 Agent 和用例生成 Agent 的协作过程。</p>}

      <h3 className="subsection-title">优化 Agent 轨迹</h3>
      {trace.length ? trace.map((step, index) => (
        <div className="trace" key={index}>
          <b>第 {step.round} 轮 · {step.action}</b>
          <span>{step.score == null ? '' : `评分 ${step.score}`}</span>
          <p>{step.summary}</p>
        </div>
      )) : <p className="empty">启动 Agent 优化后，这里会展示评估、修正和结束步骤。</p>}
      {sources.length > 0 && <div className="sources"><h4>知识库来源</h4>{sources.map((source) => <span key={source}>{source}</span>)}</div>}
      {suggestedRules.length > 0 && (
        <div className="rule-suggestions">
          <div className="card-head compact-head">
            <h4>可沉淀规则</h4>
            <button onClick={onSaveRules} disabled={busy}>沉淀到知识库</button>
          </div>
          {suggestedRules.map((rule, index) => (
            <div className="rule-item" key={`${rule.scene}-${index}`}>
              <b>{rule.scene}</b>
              <p>{rule.rule}</p>
              <span>{rule.source} · {rule.confidence}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function KnowledgeView({ items, busy, docType, setDocType, collection, onSwitchCollection, onRefresh, onUpload, onDelete }) {
  const isHistory = collection === 'history'

  return (
    <section className="card">
      <div className="card-head">
        <h3>{isHistory ? '历史用例库' : '知识文档'}</h3>
        <div className="actions">
          <div className="tabs">
            <button className={!isHistory ? 'active' : ''} onClick={() => onSwitchCollection('knowledge')}>知识文档</button>
            <button className={isHistory ? 'active' : ''} onClick={() => onSwitchCollection('history')}>历史用例</button>
          </div>
          {!isHistory && (
            <>
              <select className="compact-select" value={docType} onChange={(e) => setDocType(e.target.value)}>
                {DOC_TYPES.map((type) => <option value={type} key={type}>{type}</option>)}
              </select>
              <label className="upload">上传知识<input type="file" accept=".txt,.md,.pdf" onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0], docType)} /></label>
            </>
          )}
          <button onClick={() => onRefresh(collection)} disabled={busy}>刷新列表</button>
        </div>
      </div>

      {!isHistory && (
        <div className="kb-summary">
          {DOC_TYPES.map((type) => <span key={type}>{type}：{items.filter((item) => (item.doc_type || item['类型']) === type).length}</span>)}
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{isHistory ? '历史用例标题' : '文件名/标题'}</th>
              <th>摘要</th>
              <th>类型</th>
              <th>录入时间</th>
              <th>ID</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.ID}>
                <td>{item['文件名/标题'] || item.title || '-'}</td>
                <td>{item['AI摘要'] || item.summary || '-'}</td>
                <td><span className="type-tag">{isHistory ? '历史用例' : (item.doc_type || item['类型'] || '-')}</span></td>
                <td>{item['录入时间'] || item.date || '-'}</td>
                <td className="mono">{item.ID}</td>
                <td><button onClick={() => onDelete(item.ID, collection)}>删除</button></td>
              </tr>
            ))}
            {!items.length && (
              <tr>
                <td colSpan="6" className="empty">
                  {isHistory ? '暂无历史用例。在工作台生成用例后，可点击“保存为历史用例”。' : '暂无知识文档，请先上传业务规则、需求规范或历史缺陷记录。'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function HistoryView({ history, onRestore, onClear }) {
  return (
    <section className="card">
      <div className="card-head">
        <h3>本地历史任务</h3>
        <button onClick={onClear} disabled={!history.length}>清空历史</button>
      </div>
      <div className="history-list">
        {history.map((item) => (
          <div className="history-item" key={item.id}>
            <div>
              <b>{item.label}</b>
              <p>{new Date(item.createdAt).toLocaleString()} · {item.cases?.length || 0} 条用例</p>
            </div>
            <div className="history-metrics">
              <span>评分 {item.score ?? item.report?.score ?? '--'}</span>
              <span>轮次 {item.rounds ?? item.trace?.length ?? 0}</span>
            </div>
            <button onClick={() => onRestore(item)}>恢复</button>
          </div>
        ))}
        {!history.length && <p className="empty">暂无本地历史任务</p>}
      </div>
    </section>
  )
}

createRoot(document.getElementById('root')).render(<App />)
