import React from 'react'

interface State {
  hasError: boolean
}

export default class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  State
> {
  constructor(props: { children: React.ReactNode }) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info.componentStack)
  }

  private handleReload = () => {
    window.location.reload()
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center h-screen bg-gray-50 dark:bg-gray-900">
          <div className="text-center px-6">
            <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100 mb-2">
              予期しないエラーが発生しました
            </h1>
            <p className="text-gray-500 dark:text-gray-400 mb-6">
              問題が解決しない場合は、管理者にお問い合わせください。
            </p>
            <button
              onClick={this.handleReload}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
            >
              ページを再読み込み
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
