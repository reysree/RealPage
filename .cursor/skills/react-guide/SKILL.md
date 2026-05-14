# React Skill
# Context-Aware Message Sending Bot

## Purpose

This skill is read by the Developer Agent before writing any frontend code.
It defines every React pattern, standard, and anti-pattern for this project.

Do not invent syntax. Do not use patterns not shown here.
If a situation is not covered, ask before proceeding.

---

## Environment

```
React:        19.2.6
React DOM:    19.2.6
Vite:         8.0.12
ESLint:       10.3.0
Plugin:       eslint-plugin-react-hooks 7.1.1
              eslint-plugin-react-refresh 0.5.2
Styling:      Tailwind CSS (directives in index.css)
Language:     JSX (no TypeScript)
```

Build commands:
```
npm run dev      → start dev server (Vite)
npm run build    → production build
npm run lint     → run ESLint
npm run preview  → preview production build
```

---

## File Layout

```
frontend/src/
    App.jsx      → Chat UI: message thread, tool badges, input
    api.js       → sendMessage() and clearSession() — no fetch() in components
    main.jsx     → React DOM entry point (createRoot)
    index.css    → Tailwind directives only
```

One component per file. No barrel exports. No fetch() calls outside `api.js`.

---

## Component Rules

### Functional components only — no class components

```jsx
// Good
function MessageThread({ messages }) {
  return <ul>{messages.map(m => <Message key={m.id} {...m} />)}</ul>
}

// Bad
class MessageThread extends React.Component { ... }
```

### Props destructured in the signature

```jsx
// Good
function Message({ role, content, tools }) { ... }

// Bad
function Message(props) {
  const role = props.role
  ...
}
```

### Keys on list items — always stable, never index

```jsx
// Good — stable ID from data
messages.map(m => <Message key={m.id} {...m} />)

// Bad — index as key causes incorrect reconciliation on reorder/delete
messages.map((m, i) => <Message key={i} {...m} />)
```

---

## State Management

### useState — local UI state only

```jsx
const [input, setInput] = useState("")
const [messages, setMessages] = useState([])
const [isPending, setIsPending] = useState(false)
```

### Updating arrays — always return new arrays, never mutate

```jsx
// Good
setMessages(prev => [...prev, newMessage])
setMessages(prev => prev.filter(m => m.id !== id))

// Bad — mutates state in place
messages.push(newMessage)
setMessages(messages)
```

### useActionState — for async actions with loading/error state (React 19)

Use instead of manual `isLoading + error + data` state triples.

```jsx
import { useActionState } from "react"

const [state, submitAction, isPending] = useActionState(
  async (prevState, formData) => {
    const result = await sendMessage(formData.get("message"))
    return { response: result, error: null }
  },
  { response: null, error: null }
)
```

### useOptimistic — immediate UI feedback before async completes (React 19)

```jsx
import { useOptimistic } from "react"

const [optimisticMessages, addOptimisticMessage] = useOptimistic(
  messages,
  (state, newMessage) => [...state, newMessage]
)

async function handleSend(text) {
  addOptimisticMessage({ role: "user", content: text, pending: true })
  await sendMessage(text)
}
```

### useFormStatus — form pending state without prop drilling (React 19)

Only works inside a `<form>` with an action. Must be in a child component of the form.

```jsx
import { useFormStatus } from "react-dom"

function SubmitButton() {
  const { pending } = useFormStatus()
  return <button disabled={pending}>{pending ? "Sending…" : "Send"}</button>
}
```

---

## Fetching and Side Effects

### API calls belong in api.js — never inline fetch in components

```js
// api.js — Good
export async function sendMessage(sessionId, message) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
```

```jsx
// App.jsx — Good
import { sendMessage } from "./api.js"

// Bad — fetch() directly in component
const res = await fetch("/api/chat", { ... })
```

### useEffect — only for external sync (DOM, timers, subscriptions)

Not a data-fetching hook. Data fetching goes through actions or event handlers.

```jsx
// Good — scroll to bottom when messages change
useEffect(() => {
  bottomRef.current?.scrollIntoView({ behavior: "smooth" })
}, [messages])

// Bad — fetching inside useEffect
useEffect(() => {
  fetch("/api/data").then(...)
}, [])
```

### Cleanup effects that start subscriptions or timers

```jsx
useEffect(() => {
  const id = setInterval(poll, 3000)
  return () => clearInterval(id)  // cleanup required
}, [])
```

---

## Event Handling

### Handlers named handle* for events, on* for props

```jsx
// Good
function App() {
  function handleSubmit(e) { ... }
  return <Form onSubmit={handleSubmit} />
}

function Form({ onSubmit }) {
  return <form onSubmit={onSubmit}>...</form>
}
```

### Prevent default explicitly for forms

```jsx
function handleSubmit(e) {
  e.preventDefault()
  // ...
}
```

---

## Refs

### React 19: ref is a prop — no forwardRef needed

```jsx
// Good (React 19)
function Input({ ref, ...props }) {
  return <input ref={ref} {...props} />
}

// Bad — forwardRef is legacy in React 19
const Input = React.forwardRef((props, ref) => <input ref={ref} {...props} />)
```

### Refs for DOM access only — not for storing state

```jsx
// Good — ref to scroll container
const bottomRef = useRef(null)
bottomRef.current?.scrollIntoView()

// Bad — using ref to avoid re-render (hides state bugs)
const countRef = useRef(0)
countRef.current += 1  // component won't re-render
```

---

## Context

### React 19: use Context directly as provider — no .Provider

```jsx
// Good (React 19)
const ThemeContext = createContext("light")

function App() {
  return (
    <ThemeContext value="dark">
      <Page />
    </ThemeContext>
  )
}

// Bad — .Provider is legacy in React 19
<ThemeContext.Provider value="dark">
```

### Read context with use() for conditional reads (React 19)

```jsx
import { use } from "react"

function Message({ theme }) {
  // use() can be called inside if/loops unlike useContext
  const value = use(ThemeContext)
  return <div className={value}>...</div>
}
```

---

## Styling — Tailwind

Apply classes directly. No inline style objects unless value is dynamic and not coverable by Tailwind.

```jsx
// Good
<button className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
  Send
</button>

// Acceptable — truly dynamic value
<div style={{ height: `${scrollOffset}px` }} />

// Bad — static styles as inline objects
<button style={{ padding: "8px 16px", background: "blue" }}>
```

Conditional classes with template literals or a utility:

```jsx
// Good
<div className={`message ${role === "user" ? "bg-blue-100" : "bg-gray-100"}`}>

// Bad — building className with concatenation
<div className={"message " + (role === "user" ? "bg-blue-100" : "bg-gray-100")}>
```

---

## Anti-Patterns — Never Do These

```jsx
// 1. Mutating state directly
state.messages.push(msg)          // Bad — use setMessages(prev => [...prev, msg])

// 2. Index as key in dynamic lists
items.map((x, i) => <Item key={i} />)   // Bad — use stable IDs

// 3. fetch() inside a component body
const res = await fetch("/api/chat")     // Bad — use api.js functions

// 4. useEffect for data fetching
useEffect(() => { fetch(...) }, [])      // Bad — use action handlers

// 5. Derived state in useState (value already computable from props/state)
const [fullName, setFullName] = useState(`${first} ${last}`)  // Bad — compute inline

// 6. Missing dependency array on useEffect (runs every render)
useEffect(() => { doSomething() })       // Bad — add [] or correct deps

// 7. Stale closure in useEffect — reading state without including it in deps
useEffect(() => {
  const id = setInterval(() => console.log(count), 1000)  // Bad — count is stale
  return () => clearInterval(id)
}, [])  // Missing: count

// 8. forwardRef (legacy) — just pass ref as a prop in React 19
const Input = React.forwardRef((props, ref) => ...)  // Bad in React 19

// 9. Context.Provider (legacy) — use Context directly in React 19
<MyContext.Provider value={val}>  // Bad in React 19

// 10. propTypes — removed in React 19
MyComponent.propTypes = { ... }   // Bad — removed, use JSDoc or TypeScript

// 11. defaultProps on function components — removed in React 19
MyComponent.defaultProps = { ... }  // Bad — use default parameter values

// 12. String refs — removed in React 19
<input ref="myInput" />           // Bad — use useRef()

// 13. ReactDOM.render — removed in React 19
ReactDOM.render(<App />, root)    // Bad — use createRoot().render()

// 14. Inline arrow functions creating new references on every render (in loops)
items.map(item => (
  <button onClick={() => handleClick(item.id)}>...</button>  // Fine for simple cases,
))                                                            // but avoid in large lists

// 15. Conditional hook calls
if (condition) {
  const [x] = useState(0)  // Bad — hooks must be called unconditionally
}
```

---

## main.jsx — Entry Point Pattern

```jsx
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "./index.css"
import App from "./App.jsx"

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
)
```

- Always wrap in `StrictMode` in development
- Never call `ReactDOM.render()` — it is removed in React 19
