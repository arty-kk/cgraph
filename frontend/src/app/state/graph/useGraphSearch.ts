import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  NodeSearchItem,
  SemanticSearchItem,
  TextSearchMatch,
  TextSearchResult,
} from '@/api'
import { searchNodes, searchProjectSemantic, searchProjectText } from '@/api'
import {
  extractError,
  getSemanticSearchErrorReason,
  type SemanticSearchErrorReason,
} from '@/shared/lib/errors'
import { useNotifications } from '../session'
import { useWorkspace } from '../workspace'

/**
 * Owns semantic + text search state and their query handlers (with sequence
 * guards, semantic->path fallback, and "clear when query empties" effects).
 * Extracted verbatim from useStubGraphApp; notifications + active project come
 * from context.
 */
export function useGraphSearch() {
  const { notifyInfo, setErrorMessage } = useNotifications()
  const { activeProject } = useWorkspace().state
  const searchSeqRef = useRef(0)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<NodeSearchItem[]>([])
  const [searchSemanticResults, setSearchSemanticResults] = useState<SemanticSearchItem[]>([])
  const [searchBusy, setSearchBusy] = useState(false)
  const [semanticSearchEnabled, setSemanticSearchEnabled] = useState(false)
  const [semanticSearchFallbackUsed, setSemanticSearchFallbackUsed] = useState(false)
  const [semanticSearchUnavailableReason, setSemanticSearchUnavailableReason] = useState<SemanticSearchErrorReason | null>(null)

  const textSearchSeqRef = useRef(0)
  const [textSearchQuery, setTextSearchQuery] = useState('')
  const [textSearchResults, setTextSearchResults] = useState<TextSearchMatch[]>([])
  const [textSearchMeta, setTextSearchMeta] = useState<TextSearchResult['meta'] | null>(null)
  const [textSearchBusy, setTextSearchBusy] = useState(false)
  const [textSearchCaseSensitive, setTextSearchCaseSensitive] = useState(false)
  const [textSearchPrefix, setTextSearchPrefix] = useState('')
  const [textSearchError, setTextSearchError] = useState<string | null>(null)

  useEffect(() => {
    if (searchQuery.trim()) return
    if (searchResults.length === 0) return
    setSearchResults([])
  }, [searchQuery, searchResults.length])

  useEffect(() => {
    if (searchQuery.trim()) return
    if (searchSemanticResults.length === 0) return
    setSearchSemanticResults([])
  }, [searchQuery, searchSemanticResults.length])

  useEffect(() => {
    setSearchResults([])
    setSearchSemanticResults([])
    setSemanticSearchFallbackUsed(false)
  }, [semanticSearchEnabled])

  useEffect(() => {
    if (textSearchQuery.trim()) return
    if (textSearchResults.length === 0 && !textSearchMeta && !textSearchError) return
    setTextSearchResults([])
    setTextSearchMeta(null)
    setTextSearchError(null)
  }, [textSearchError, textSearchMeta, textSearchQuery, textSearchResults.length])

  const onSearchNodes = useCallback(
    async (query: string) => {
      if (!activeProject) return
      setSearchQuery(query)
      setSemanticSearchFallbackUsed(false)
      if (!query.trim()) {
        searchSeqRef.current++
        setSearchBusy(false)
        setSearchResults([])
        setSearchSemanticResults([])
        return
      }
      const seq = ++searchSeqRef.current
      setSearchBusy(true)
      try {
        if (semanticSearchEnabled) {
          const res = await searchProjectSemantic(activeProject.id, query, 30)
          if (searchSeqRef.current !== seq) return
          const semanticResults = res.results ?? []
          if (semanticResults.length === 0) {
            const fallbackRes = await searchNodes(activeProject.id, query, 30)
            if (searchSeqRef.current !== seq) return
            setSearchResults(fallbackRes)
            setSearchSemanticResults([])
            setSemanticSearchFallbackUsed(true)
            notifyInfo('Semantic search returned no results — showing path search instead.')
          } else {
            setSearchSemanticResults(semanticResults)
            setSearchResults([])
          }
          if (searchSeqRef.current !== seq) return
          setSemanticSearchUnavailableReason(null)
        } else {
          const res = await searchNodes(activeProject.id, query, 30)
          if (searchSeqRef.current !== seq) return
          setSearchResults(res)
          setSearchSemanticResults([])
        }
      } catch (e: any) {
        if (searchSeqRef.current !== seq) return
        const reason = semanticSearchEnabled ? getSemanticSearchErrorReason(e) : null
        if (semanticSearchEnabled && reason) {
          setSemanticSearchEnabled(false)
          setSemanticSearchUnavailableReason(reason)
          if (reason === 'no_embeddings') {
            notifyInfo('Project embeddings are missing — run Scan with embeddings enabled.')
          }
          try {
            const res = await searchNodes(activeProject.id, query, 30)
            if (searchSeqRef.current !== seq) return
            setSearchResults(res)
            setSearchSemanticResults([])
            notifyInfo('Semantic search is unavailable — using standard search.')
          } catch (fallbackError: any) {
            setErrorMessage(extractError(fallbackError))
          }
        } else {
          setErrorMessage(extractError(e))
        }
      } finally {
        if (searchSeqRef.current === seq) setSearchBusy(false)
      }
    },
    [activeProject, notifyInfo, semanticSearchEnabled, setErrorMessage]
  )

  const onSearchText = useCallback(
    async (queryInput: string) => {
      if (!activeProject) return
      const query = String(queryInput || '').trim()
      setTextSearchQuery(query)
      if (!query) {
        textSearchSeqRef.current++
        setTextSearchBusy(false)
        setTextSearchResults([])
        setTextSearchMeta(null)
        setTextSearchError(null)
        return
      }
      const seq = ++textSearchSeqRef.current
      setTextSearchBusy(true)
      setTextSearchError(null)
      try {
        const res = await searchProjectText(activeProject.id, query, {
          prefix: textSearchPrefix.trim() || undefined,
          case_sensitive: textSearchCaseSensitive,
        })
        if (textSearchSeqRef.current !== seq) return
        setTextSearchResults(res.matches || [])
        setTextSearchMeta(res.meta || null)
      } catch (e: any) {
        if (textSearchSeqRef.current !== seq) return
        setTextSearchError(extractError(e))
      } finally {
        if (textSearchSeqRef.current === seq) setTextSearchBusy(false)
      }
    },
    [activeProject, textSearchCaseSensitive, textSearchPrefix],
  )

  return {
    searchQuery,
    setSearchQuery,
    searchResults,
    setSearchResults,
    searchSemanticResults,
    setSearchSemanticResults,
    searchBusy,
    semanticSearchEnabled,
    setSemanticSearchEnabled,
    semanticSearchFallbackUsed,
    semanticSearchUnavailableReason,
    textSearchQuery,
    setTextSearchQuery,
    textSearchResults,
    textSearchMeta,
    textSearchBusy,
    textSearchCaseSensitive,
    setTextSearchCaseSensitive,
    textSearchPrefix,
    setTextSearchPrefix,
    textSearchError,
    onSearchNodes,
    onSearchText,
  }
}
