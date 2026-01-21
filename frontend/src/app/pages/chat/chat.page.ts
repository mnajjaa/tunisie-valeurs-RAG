import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, ElementRef, NgZone, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TimeoutError, firstValueFrom } from 'rxjs';

import { AskService, AskSource } from '../../core/api/ask.service';

type MessageRole = 'user' | 'assistant' | 'error';

interface ChatMessage {
  role: MessageRole;
  content: string;
  sources: AskSource[];
}

@Component({
  selector: 'app-chat-page',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './chat.page.html',
  styleUrl: './chat.page.scss'
})
export class ChatPage {
  @ViewChild('scrollContainer') private scrollContainer?: ElementRef<HTMLDivElement>;

  messages: ChatMessage[] = [];
  draft = '';
  loading = false;

  constructor(
    private readonly askService: AskService,
    private readonly zone: NgZone
  ) {}

  async sendMessage(): Promise<void> {
    const question = this.draft.trim();
    if (!question || this.loading) {
      return;
    }

    this.messages.push({ role: 'user', content: question, sources: [] });
    this.draft = '';
    this.loading = true;
    this.queueScroll();

    try {
      const response = await firstValueFrom(this.askService.ask(question, 6, null));
      this.zone.run(() => {
        this.messages.push({
          role: 'assistant',
          content: response.answer,
          sources: response.sources ?? []
        });
      });
    } catch (error) {
      this.zone.run(() => {
        this.messages.push({
          role: 'error',
          content: this.formatError(error),
          sources: []
        });
      });
    } finally {
      this.zone.run(() => {
        this.loading = false;
        this.queueScroll();
      });
    }
  }

  handleKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Enter' || event.shiftKey) {
      return;
    }

    event.preventDefault();
    this.sendMessage();
  }

  private queueScroll(): void {
    setTimeout(() => this.scrollToBottom(), 0);
  }

  private formatError(error: unknown): string {
    if (error instanceof TimeoutError) {
      return 'The request timed out. Please try again.';
    }
    if (error instanceof HttpErrorResponse) {
      if (error.status === 0) {
        return 'Network error. Check that the API is reachable and CORS is enabled.';
      }
      if (error.error?.detail) {
        return `Error ${error.status}: ${error.error.detail}`;
      }
      return `Error ${error.status}: ${error.message}`;
    }
    return 'Sorry, the request failed. Please try again.';
  }

  private scrollToBottom(): void {
    const container = this.scrollContainer?.nativeElement;
    if (!container) {
      return;
    }
    container.scrollTop = container.scrollHeight;
  }
}
