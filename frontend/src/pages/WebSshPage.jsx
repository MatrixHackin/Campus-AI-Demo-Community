import '@xterm/xterm/css/xterm.css'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Terminal } from '@xterm/xterm'
import { getWebSshSocketUrl } from '../api/client'
import AppShell from '../components/AppShell'

function parseTarget(target = '') {
  const index = target.lastIndexOf('+')
  if (index <= 0 || index === target.length - 1) {
    return null
  }
  return {
    appName: target.slice(0, index),
    sshUsername: target.slice(index + 1)
  }
}

export default function WebSshPage() {
  const { target } = useParams()
  const terminalRef = useRef(null)
  const [status, setStatus] = useState('connecting')
  const parsedTarget = useMemo(() => parseTarget(target), [target])

  useEffect(() => {
    if (!parsedTarget || !terminalRef.current) {
      setStatus('error')
      return undefined
    }

    const terminal = new Terminal({
      cursorBlink: true,
      convertEol: true,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
      fontSize: 14,
      theme: {
        background: '#08111f',
        foreground: '#dbeafe',
        cursor: '#70a6ff'
      }
    })
    terminal.open(terminalRef.current)
    terminal.writeln(`Connecting to ${parsedTarget.sshUsername}@${parsedTarget.appName} ...`)

    const socket = new WebSocket(getWebSshSocketUrl(parsedTarget.appName, parsedTarget.sshUsername))

    socket.addEventListener('open', () => {
      setStatus('connected')
      terminal.writeln('Connected.')
    })

    socket.addEventListener('message', (event) => {
      terminal.write(event.data)
    })

    socket.addEventListener('close', () => {
      setStatus('closed')
      terminal.writeln('\r\nConnection closed.')
    })

    socket.addEventListener('error', () => {
      setStatus('error')
      terminal.writeln('\r\nConnection error.')
    })

    const disposable = terminal.onData((data) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(data)
      }
    })

    return () => {
      disposable.dispose()
      socket.close()
      terminal.dispose()
    }
  }, [parsedTarget])

  return (
    <AppShell>
      <section className="webssh-panel" aria-labelledby="webssh-title">
        <div className="webssh-panel__header">
          <div>
            <h1 id="webssh-title">WebSSH</h1>
            <p>{parsedTarget ? `${parsedTarget.sshUsername}@${parsedTarget.appName}` : '连接地址不合法'}</p>
          </div>
          <span className={`webssh-status webssh-status--${status}`}>{status}</span>
        </div>
        <div className="webssh-terminal" ref={terminalRef} />
      </section>
    </AppShell>
  )
}
