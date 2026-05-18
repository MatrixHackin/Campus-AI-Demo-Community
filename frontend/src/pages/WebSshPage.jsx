import '@xterm/xterm/css/xterm.css'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { getWebSshSocketUrl } from '../api/client'
import AppShell from '../components/AppShell'

function parseTarget(target = '') {
  // app_name 本身只允许小写字母/数字/中划线，不包含 `+`；
  // username 理论上可能包含 `+`，因此必须按第一个 `+` 分隔。
  const index = target.indexOf('+')
  if (index <= 0 || index === target.length - 1) {
    return null
  }
  return {
    appName: target.slice(0, index),
    sshUsername: target.slice(index + 1)
  }
}

function sendSocketMessage(socket, message) {
  if (socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(message))
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
      scrollback: 8000,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
      fontSize: 14,
      theme: {
        background: '#08111f',
        foreground: '#dbeafe',
        cursor: '#70a6ff'
      }
    })
    const fitAddon = new FitAddon()
    terminal.loadAddon(fitAddon)
    terminal.open(terminalRef.current)
    fitAddon.fit()
    terminal.writeln(`Connecting to ${parsedTarget.sshUsername}@${parsedTarget.appName} ...`)

    const socket = new WebSocket(getWebSshSocketUrl(parsedTarget.appName, parsedTarget.sshUsername))
    const writeQueue = []
    let writing = false

    const pumpWriteQueue = () => {
      if (writing || writeQueue.length === 0) return
      writing = true
      terminal.write(writeQueue.shift(), () => {
        writing = false
        pumpWriteQueue()
      })
    }

    const queueTerminalWrite = (data) => {
      writeQueue.push(data)
      pumpWriteQueue()
    }

    const sendResize = () => {
      sendSocketMessage(socket, {
        type: 'resize',
        cols: terminal.cols,
        rows: terminal.rows
      })
    }

    socket.addEventListener('open', () => {
      setStatus('connected')
      terminal.writeln('Connected.')
      fitAddon.fit()
      sendResize()
    })

    socket.addEventListener('message', (event) => {
      queueTerminalWrite(event.data)
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
      sendSocketMessage(socket, { type: 'data', data })
    })

    const resizeObserver = new ResizeObserver(() => {
      fitAddon.fit()
      sendResize()
    })
    resizeObserver.observe(terminalRef.current)

    return () => {
      resizeObserver.disconnect()
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
