import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, timeout } from 'rxjs';

import { environment } from '../../../environments/environment';

export interface AskRequest {
  question: string;
  top_k: number;
  document_id: number | null;
}

export interface AskSource {
  document_id: number;
  title: string;
  page: number;
  score: number;
  text_preview: string;
}

export interface AskResponse {
  answer: string;
  sources: AskSource[];
}

@Injectable({
  providedIn: 'root'
})
export class AskService {
  private readonly endpoint = `${environment.apiBaseUrl}/api/ask`;

  constructor(private readonly http: HttpClient) {}

  ask(question: string, topK = 6, documentId: number | null = null): Observable<AskResponse> {
    const payload: AskRequest = {
      question,
      top_k: topK,
      document_id: documentId
    };

    return this.http.post<AskResponse>(this.endpoint, payload).pipe(
      timeout({ first: 120000 })
    );
  }
}
