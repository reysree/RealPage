import { HashRouter, Routes, Route } from 'react-router-dom'
import OutreachRunner from './OutreachRunner.jsx'
import PersonalCodeMapFallback from './PersonalCodeMapFallback.jsx'

const codeMapModules = import.meta.glob('./personal/CodeMapReview.jsx', { eager: true })
const CodeMapReview =
  codeMapModules['./personal/CodeMapReview.jsx']?.default ?? PersonalCodeMapFallback

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<OutreachRunner />} />
        <Route path="/personal/code-map" element={<CodeMapReview />} />
      </Routes>
    </HashRouter>
  )
}
