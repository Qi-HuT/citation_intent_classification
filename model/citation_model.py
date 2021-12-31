# -*t coding: utf-8 -*-
import torch
import torch.nn as nn
from transformers import AutoModel
import numpy as np
import torch.nn.functional as F


class Model(nn.Module):
    def __init__(self, name, temp=0.2):
        super(Model, self).__init__()
        self.model = AutoModel.from_pretrained(name)
        self.temp=temp
        self.fc1 = nn.Linear(768 * 2, 768)
        self.mix_fc = nn.Linear(768, 192)
        self.fc = nn.Linear(768, 6)
        self.drop = nn.Dropout(0.5)

        self.au_task_fc1 = nn.Linear(768, 5)

        self.ori_word_atten = nn.Linear(768, 384)
        self.ori_tanh = nn.Tanh()
        self.ori_word_weight = nn.Linear(384, 1, bias=False)

        self.re_word_atten = nn.Linear(768, 384)
        self.re_tanh = nn.Tanh()
        self.re_word_weight = nn.Linear(384, 1, bias=False)

    # Calculate the weight of each word
    def get_alpha(self, word_mat, data_type, mask):
        if data_type == 'ori':
            # representation learning  attention
            att_w = self.ori_word_atten(word_mat)
            att_w = self.ori_tanh(att_w)
            att_w = self.ori_word_weight(att_w)
        else:
            # classification learning  attention
            att_w = self.re_word_atten(word_mat)
            att_w = self.re_tanh(att_w)
            att_w = self.re_word_weight(att_w)

        mask = mask.unsqueeze(2)
        att_w = att_w.masked_fill(mask == 0, float('-inf'))
        att_w = F.softmax(att_w, dim=1)
        return att_w

    # Get useful words vectors
    def get_word(self, sen, bert_output, mask):
        input_t2n = sen['input_ids'].cpu().numpy()
        sep_location = np.argwhere(input_t2n == 103)
        sep_location = sep_location[:, -1]
        select_index = list(range(sen['length'][0]))
        select_index.remove(0)  # 删除cls
        lhs = bert_output.last_hidden_state
        res = bert_output.hidden_states[8]
        relength = []
        recomposing = []
        mask_recomposing = []
        for i in range(lhs.shape[0]):
            select_index_f = select_index.copy()
            relength.append(sep_location[i] - 1)
            select_index_f.remove(sep_location[i])
            select_row = torch.index_select(lhs[i], 0, index=torch.LongTensor(select_index_f).to(sen['input_ids'].device))
            select_mask = torch.index_select(mask[i], 0, index=torch.LongTensor(select_index_f).to(sen['input_ids'].device))
            recomposing.append(select_row)
            mask_recomposing.append(select_mask)
        matrix = torch.stack(recomposing)
        mask = torch.stack(mask_recomposing)
        return matrix,  mask

    # Get the representation vector after calculating the attention mechanism
    def get_sen_att(self, sen, bert_output, data_type, mask):
        word_mat,  select_mask = self.get_word(sen, bert_output, mask)
        word_mat = self.drop(word_mat)
        att_w = self.get_alpha(word_mat, data_type, select_mask)
        word_mat = word_mat.permute(0, 2, 1)
        sen_pre = torch.bmm(word_mat, att_w).squeeze(2)
        return sen_pre

    # def forward(self, x1, **kwargs):
    #     input_ids = x1['input_ids']
    #     batch_size = input_ids.shape[0]
    #     attention_mask = x1['attention_mask']
    #     bert_output = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
    #     ori_sen_pre = self.get_sen_att(x1, bert_output, 'ori', attention_mask)
    #
    #     if self.training:
    #         # Obtain the representation vector for the classification learning branch
    #         r_ids = kwargs['r_sen']['input_ids']
    #         r_attention_mask = kwargs['r_sen']['attention_mask']
    #         r_bert_output = self.model(r_ids, attention_mask=r_attention_mask, output_hidden_states=True)
    #         re_sen_pre = self.get_sen_att(kwargs['r_sen'], r_bert_output, 're', r_attention_mask)
    #         # Get the representation vector for the auxiliary task
    #         s_ids = kwargs['s_sen']['input_ids']
    #         s_attention_mask = kwargs['s_sen']['attention_mask']
    #         s_bert_output = self.model(s_ids, attention_mask=s_attention_mask, output_hidden_states=True)
    #         ausec_sen_pre = self.get_sen_att(kwargs['s_sen'], s_bert_output, 'ori', s_attention_mask)
    #
    #         ori_sen_pre = self.drop(ori_sen_pre)
    #         re_sen_pre = self.drop(re_sen_pre)
    #         # Splice the representation vectors of both branches
    #         mixed_feature = 2 * torch.cat((kwargs['l'] * ori_sen_pre, (1 - kwargs['l']) * re_sen_pre), dim=1)
    #         main_output = self.fc1(self.drop(mixed_feature))
    #         main_output = self.fc(main_output)
    #         au_output1 = self.au_task_fc1(self.drop(ausec_sen_pre))
    #         return main_output, au_output1
    #     re_sen_pre = self.get_sen_att(x1, bert_output, 're', attention_mask)
    #     mixed_feature = torch.cat((ori_sen_pre, re_sen_pre), dim=1)
    #     mixed_feature = self.fc1(mixed_feature)
    #     mixed_feature = self.fc(mixed_feature)
    #     return mixed_feature

    # forward for i-mix
    def forward(self, x1, **kwargs):
        input_ids = x1['input_ids']
        batch_size = input_ids.shape[0]
        attention_mask = x1['attention_mask']
        bert_output = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
        ori_sen_pre = self.get_sen_att(x1, bert_output, 'ori', attention_mask)

        if self.training:
            bert_output_mix = self.drop(bert_output)
            # for i-mix
            bert_output_imix = self.model(input_ids, attention_mask=attention_mask, output_hidden_states=True)
            bert_output_imix = self.drop(bert_output_imix)
            bert_output_mix, labels_aux, lam = self.imix(bert_output_mix, kwargs['mix_alpha'])
            tem_ori_pre = torch.cat([bert_output_mix, bert_output_imix], dim=0)
            attention_mask = torch.cat([attention_mask, attention_mask], dim=0)
            tem_ori_pre = self.get_sen_att(tem_ori_pre, bert_output, 'ori', attention_mask)
            tem_ori_pre = self.mix_fc(tem_ori_pre)

            tem_ori_pre = nn.functional.normalize(tem_ori_pre, dim=1)
            bert_output_mix, bert_output_imix = tem_ori_pre[:batch_size], tem_ori_pre[batch_size:]
            mix_logits = bert_output_mix.mm(bert_output_imix.t())
            mix_logits /= self.temp
            mix_labels = torch.arange(batch_size, dtype=torch.long).cuda()
            # mix_loss = (lam * criterion(mix_logits, mix_labels) + (1. - lam) * criterion(mix_logits, labels_aux)).mean()


            # Obtain the representation vector for the classification learning branch
            r_ids = kwargs['r_sen']['input_ids']
            r_attention_mask = kwargs['r_sen']['attention_mask']
            r_bert_output = self.model(r_ids, attention_mask=r_attention_mask, output_hidden_states=True)
            re_sen_pre = self.get_sen_att(kwargs['r_sen'], r_bert_output, 're', r_attention_mask)
            # Get the representation vector for the auxiliary task
            s_ids = kwargs['s_sen']['input_ids']
            s_attention_mask = kwargs['s_sen']['attention_mask']
            s_bert_output = self.model(s_ids, attention_mask=s_attention_mask, output_hidden_states=True)
            ausec_sen_pre = self.get_sen_att(kwargs['s_sen'], s_bert_output, 'ori', s_attention_mask)

            ori_sen_pre = self.drop(ori_sen_pre)
            re_sen_pre = self.drop(re_sen_pre)
            # Splice the representation vectors of both branches
            mixed_feature = 2 * torch.cat((kwargs['l'] * ori_sen_pre, (1 - kwargs['l']) * re_sen_pre), dim=1)
            main_output = self.fc1(self.drop(mixed_feature))
            main_output = self.fc(main_output)
            au_output1 = self.au_task_fc1(self.drop(ausec_sen_pre))
            return main_output, au_output1, mix_logits, mix_labels, labels_aux, lam
        re_sen_pre = self.get_sen_att(x1, bert_output, 're', attention_mask)
        mixed_feature = torch.cat((ori_sen_pre, re_sen_pre), dim=1)
        mixed_feature = self.fc1(mixed_feature)
        mixed_feature = self.fc(mixed_feature)
        return mixed_feature

    def imix(self, input, alpha, share_lam=False):
        beta = torch.distributions.beta.Beta(*alpha)
        randind = torch.randperm(input.shape[0], device=input.device)
        if share_lam:
            lam = beta.sample().to(device=input.device)
            lam = torch.max(lam, 1. - lam)
            lam_expanded = lam
        else:
            lam = beta.sample([input.shape[0]]).to(device=input.device)
            lam = torch.max(lam, 1. - lam)
            lam_expanded = lam.view([-1] + [1] * (input.dim() - 1))
        output = lam_expanded * input + (1. - lam_expanded) * input[randind]
        return output, randind, lam