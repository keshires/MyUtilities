import { HttpClient } from '@angular/common/http';

export class EntityService {
  private base = 'https://api.example.net/edfx/v2';

  constructor(private http: HttpClient) {}

  getEntity(id: string) {
    return this.http.get(`${this.base}/entities/${id}`);
  }

  createEntity(body: any) {
    return this.http.post<Entity>(this.base + '/entities', body);
  }
}
